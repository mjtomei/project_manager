# Review Response — Cycle 10 — User-Modeling as a Lever on LLM Performance

Response to `REVIEW_CYCLE_10_USERMODEL.md`. Per methodology: each finding gets a verdict and the change to make; prior-art findings get the narrow-don't-collapse treatment; the cycle must net-cut.

---

## Prior-art verification (methodology step 5e / p.152)

The reviewer cited three Jan-2026 papers. All three were verified independently against source before being acted on. Two were mischaracterized — the verification changes the verdicts.

**Paper 1 — arXiv:2601.16644, "Sycophancy Hides Linearly in the Attention Heads"** (Genadi et al., Jan 2026, Gemma-3-4B / Llama-3.2-3B). **Real, but the reviewer overstated it.** The paper's own words: "Although separability appears in the residual stream and MLPs, steering using these probes is most effective in a sparse subset of middle-layer attention heads." So it *confirms* residual-stream separability — it does **not** contradict the plan's residual-stream assumption. What is attention-head-specific is *steering efficacy*, not probe separability (and attention-head outputs write into the residual stream anyway). It uses directional steering only — no interchange intervention.

**Paper 2 — arXiv:2601.18939, "A Few Bad Neurons"** (O'Brien et al., Jan 2026, Gemma-2-2B/9B). **Real, but the reviewer mischaracterized the overlap.** It does **not** isolate a user-side signal. It localizes the ~3% of MLP neurons most responsible for sycophantic *output behavior* and fine-tunes them via gradient masking — a behavior-localization + weight edit, not a user-representation or an inference-time steering method. Minimal overlap with H2's core.

**Paper 3 — OpenReview BCS7HHInC2, "Mitigating Sycophancy … Sparse Activation Fusion and Multi-Layer Activation Steering" (SAF/MLAS)** (Adityo et al.). **Real, but the reviewer mis-cited it: it is a NeurIPS 2025 Mechanistic Interpretability workshop paper on Gemma-2-2B — not ICLR 2026, not 9B.** It is the genuine partial preemption of the three: SAF isolates a per-query user-opinion signal, MLAS ablates residual-stream "pressure directions" and reduces sycophancy. It does not do interchange interventions, does not frame a persistent truth-seeking sub-dimension of a model-of-the-user, does not correlate the direction with accuracy, and does not touch closed models.

---

## Block 1 — Substance

### Finding 1 — "H2 is a special case of H1" overstated. **PARTIALLY ACCEPT.**
The reviewer is right that the bare phrase "special case" is too strong and is used to justify folding H2 in cheaply. H1's behavioral channel is effort-calibration; H2's is conflict-resolution (correctness vs. deference when they collide) — and a user can be high-H1 / low-H2. But "sibling with no relation" overcorrects: H2 genuinely shares H1's *mechanism* (training-data imitation) and probes a *sub-dimension of H1's own IV* (truth-seeking sits under intellectual peer-ness). **Change:** drop the literal "H2 is a special case of H1"; replace with "H2 applies H1's mechanism to one sub-dimension (truth-seeking) and a distinct failure mode (sycophancy); it shares H1's IV-structure and imitation mechanism but runs through a different behavioral channel and is tested against a different DV." Keep the shared-mechanism link — it is load-bearing for the training-data-imitation argument and is not in dispute.

### Finding 2 — attention-heads paper "contradicts the residual-stream assumption." **REJECT the strong claim; ACCEPT a minor add.**
Verification shows 2601.16644 *confirms* residual-stream separability; it does not contradict Phase 1. **Change:** cite 2601.16644 in lit review §5, and add a one-line Phase 3 implementation note that steering may be most effective in middle-layer attention heads. This is an implementation detail, **not** a Phase 1 methodological correction. Do not rewrite the residual-stream framing.

### Finding 3 — H2 contribution claim is circular. **ACCEPT.**
The claim "H2 probes truth-seeking as a dispositional attribute" pre-supposes the Phase 1 result that Phase 1 is meant to test. **Change:** make the contribution claim explicitly conditional — "*if* Phase 1 finds the probe tracks a stable disposition, H2's contribution is the dispositional-attribute framing; if it tracks per-message intent, H2 narrows toward a Cheng et al. replication on a gradable-correctness DV." The plan's Phase 1 acceptance criteria already run this test; the contribution paragraph must inherit its conditionality rather than assert the favorable branch.

### Finding 4 — "two more papers preempt H2." **PARTIALLY ACCEPT.**
Per verification: **Paper 3 (SAF/MLAS) is a genuine partial preemption** — add it to lit review §5 alongside Cheng et al., correctly cited (NeurIPS 2025 MI workshop, Gemma-2-2B). H2's residual still holds against it: interchange-intervention causal bar, a persistent truth-seeking sub-dimension of a model-of-the-user (vs. SAF's per-query prompt-contrastive bias), the accuracy correlation, and Phase 4. **Paper 2 (A Few Bad Neurons) does not preempt H2's core** — cite it, with Paper 1, as recent adjacent sycophancy-mechanism work, not as a preemption; do not narrow H2 against it.

### Finding 5 — "Resolution V" aliasing claim stated incorrectly. **ACCEPT.**
"Higher-order interactions aliased with main effects" is the Resolution III property, false for the 2^(5−1) Resolution V design the plan uses. **Change (both occurrences):** under Resolution V, main effects and two-factor interactions are each clear of *each other*; main effects are aliased only with four-factor interactions and two-factor interactions with three-factor interactions — all treated as negligible. Fix the wording so the two passages agree.

### Plan-vs-lit-review drift — Wang competence concession. **ACCEPT.**
The concession that Wang et al. predicts the intellectual-competence sub-dimension may not be linearly decodable currently lives only in the lit review. Add a one-sentence version to the plan (Phase 1 or the confounders area) so the two documents agree.

### Remaining Block 1 findings
Apply the reviewer's other Block 1 items where they are concrete and correct; the apply pass handles them against the review file's proposed wording.

## Blocks 2, 3, 4

Apply the reviewer's proposed rewrites for the non-pedantic findings. The reviewer itself flags that Block 2 and the lit-review half of Block 3 are near convergence and several Block 4 items border on pedantic — **decline** the pedantic Block 4 items per methodology step 8 (convergence signal), apply the rest. The plan-side Block 3 accessibility findings are load-bearing — apply all of them.

## Net-cut (methodology step 9)

Length is flagged. The apply pass measured before/after:

| File | Before | After |
|---|---|---|
| Plan (`plan-66d430f.md`) | 9,787 | 9,848 |
| Lit review (`literature-review-user-model.md`) | 16,641 | 16,532 |
| **Combined** | **26,428** | **26,380** |

Combined total ended **48 words lower** — a net cut, as required. The plan grew slightly (conditional H2 rewrite, the competence-concession note, the attention-head and confound-separability notes, the Tier-1 gate procedure, accessibility glosses); this was offset by trimming lit review §4 — the probe/steer/interchange restatement, the evidence-grade worked example, the discussion-order scaffolding, and the Choi / Cabello / Deas / TalkTuner per-paper paragraphs that duplicated the §4 table and §7 — plus the §5 Wang "precise reading" paragraph and the §7 neighborhood bullets. The three new citations went in as one terse paragraph in §5 and three reference entries.
