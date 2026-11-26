# Response to Review Cycle 8 — Literature Review: User-Modeling as a Lever on LLM Performance

Response author: Cycle-8 response pass. Date: 2026-05-15.

The reviewer's own convergence signal (Step-5 walk: "neither preempts the contribution claim — positive convergence signal") frames this cycle. The response below treats Block 1 as internal-claim cleanup rather than as another contribution-narrowing pass, with one exception: the B1-6 contamination finding has plan-side implications and is surfaced upward.

---

## Step 5 verification — candidate prior art

### Lu et al. 2026, "The Assistant Axis: Situating and Stabilizing the Default Persona of Language Models" (arXiv:2601.10387)

**Verified.** Authors: Christina Lu, Jack Gallagher, Jonathan Michala, Kyle Fish, Jack Lindsey (Anthropic + MATS). Submitted 15 January 2026.

Verbatim from the abstract:

> "Large language models can represent a variety of personas but typically default to a helpful Assistant identity cultivated during post-training."

The paper extracts activation directions tied to character archetypes, identifies a dominant "Assistant Axis" indicating whether the model operates in its default helpful mode, and shows that steering along this axis stabilizes behavior against drift and jailbreak attempts.

**Classification decision: model-side, parallel-axis peer.** The variable is the *model's own* Assistant-persona direction, not the model's representation of the user. This is the same side of the causal arrow as Persona Vectors (Chen 2025) and Ibrahim et al. — the IV-as-model-trait family, not the IV-as-user-model family the plan operates in.

**Where it cites: §5's model-side-traits cluster (alongside Persona Vectors and Ibrahim) and §7's neighborhood enumeration as the canonical model-side anchor that any user-side probe should control against.** It does *not* belong in the §5 / §7 cells that discuss user-perception variables, and the methodology's contribution-narrowing principle does *not* apply to it (no intersection on the variable side).

This matches the reviewer's classification — recording the verification here per the methodology's procedural rule.

### "The Non-Linear Representation Dilemma" (OpenReview 2025/2026, minor)

Could not be verified at the OpenReview ID the reviewer implied. Treat as **provisional**: cite only if a verified ID surfaces during edit application; otherwise omit. The Hernandez 2024 caveat already in §4 carries the load-bearing point without it.

---

## Block 1 — Substantive findings

### B1-1. Training-data-imitation mechanism: three unmentioned alternative mechanisms.

**Position: agree.** The reviewer identifies a real gap. The mechanism story currently chains three claims (humans calibrate by peer-ness → leaks into next-token statistics → LLMs reproduce) without naming the three alternative-but-confounding mechanisms a positive Phase 2 result is also consistent with:

1. generic high-effort-prompt → high-effort-response register-matching (Sclar-style noise floor),
2. high-status-interlocutor → cautious-output rule from corporate / formal genres,
3. RLHF post-training policy "be careful when user seems sophisticated" that bypasses pretraining-imitation.

**Edit:** Add a paragraph in §1 after the training-data-imitation passage naming these three alternatives explicitly. Update §7's alternative-mechanisms table cell (currently mentions only sycophancy) to list all three. Update the Phase 3 description: per-direction steering against independently-extracted register / status-rule / RLHF-policy directions is the explicit disambiguator. **Cross-cycle note**: per the reviewer's cross-reference appendix, this is a substantive miss across prior cycles, not just Cycle 8.

### B1-2. Phase 4 closed-model transfer inherits Phase 1's behavioral-grade bar — consequence not drawn.

**Position: agree.** §6 acknowledges Phase 4 inherits Phase 1's evidence bar but does not draw the consequence for production-facing readers. A positive Phase 4 result on a closed model is *behavioral-grade only* — it does not establish that closed models have a causally-mediating peer-ness representation, only that the verbalized self-report tracks the open-model probe.

**Edit:** Add an explicit consequence sentence in §6 and again in the conclusion: "A positive Phase 4 result on a closed model is correlationally calibrated against the open-model probe and behaviorally observable; it does not establish that the closed model has a causally-mediating peer-ness representation." Phase 4 description in the plan should mirror this.

### B1-3. Goodwin third-factor alternative named but not operationalized in Phase 1's factor analysis.

**Position: agree (narrow).** The artifact handwaves "factor analysis" without committing to a factor-retention rule.

**Edit:** Add a one-sentence pre-commitment in §7 / Phase 1 methodology: parallel analysis (Horn 1965) as the primary factor-retention rule, with BIC and Velicer's MAP as secondary. Explicitly note Kaiser's K1 is *not* used (it overstates factor count).

### B1-4. Wang's "authority" is the same SCM-competence cell as the plan's intellectual competence.

**Position: agree.** The reviewer is correct that Fiske/Cuddy/Glick/Xu 2002's competence operationalization includes "powerful" and "high status." The "partial pre-replication target" framing overstates the construct distance between Wang's authority probe and the plan's intellectual-competence dimension.

**Edit:** Soften §5's Wang passage. Replace "partial pre-replication target" with: "Wang's authority probe likely loads on the SCM competence dimension; a Phase 1 null on intellectual competence would be the expected outcome given Wang, not a surprise. Phase 1's residual contribution against Wang is therefore (a) the contrast-pair extraction methodology Wang didn't use, (b) the multi-cell SCM coverage (warmth as well as competence), and (c) the task-performance DV rather than authority-recognition as the readout." This narrows but does not collapse the Wang framing.

### B1-5. Multiple comparisons / power unmentioned.

**Position: partial agree.** Procedurally borderline — the reviewer concedes this is more plan-level than lit-review-level. But the lit review's predicted-outcome table has six rows, each implicitly a hypothesis, so flagging is warranted.

**Edit:** Add one sentence in §7's fractional-factorial subsection on family-wise error control (Holm-Bonferroni on per-sub-dimension main effects, BH-FDR on interactions) as a precondition for the table's rows being interpretable as independent findings. Surface to the plan as a methodology note.

### B1-6. MMLU/HumanEval contamination buried at end of §8; should escalate to non-contaminated primary DV.

**Position: agree.** Contamination has potentially nullified Phase 2's headroom on MMLU items the model already gets right. Burying this at the tail of §8 understates the risk.

**Edit (lit review):** Move the contamination passage from §8 to §1 (mechanism + measurement section) and to §7 (predicted-outcome table). Reframe: name a non-contaminated benchmark as *primary* DV — LiveBench, SWE-Bench Verified, or BBH-extra are the candidates; MMLU and GSM8K become *secondary* anchors-to-prior-literature.

**Plan-side surfacing:** This is a methodology recommendation to plan-66d430f.md. Proposed plan edit (separate change, not in this cycle's response): add to Phase 2 methodology section an explicit "primary DV: non-contaminated recent benchmark (LiveBench / SWE-Bench Verified / BBH-extra); secondary anchor DVs: MMLU, GSM8K, HumanEval treated as relative-movement signals under matched-content paraphrases only." Flagging here so the plan owner can decide.

---

## Block 2 — Structural / readability findings

Rollup. All five are accepted as written; edits are mechanical.

- **B2-1** §4 length / vocabulary-first ordering: defer the full §4 glossary to end-of-section; gloss each interpretability term inline on first use. Consider §4a (probing) / §4b (causal) split if word budget permits.
- **B2-2** glossary duplication §1 / §4: add a single top-of-document glossary pointer, or a "see §4 for interpretability vocabulary" forward reference in §1.
- **B2-3** §7 buried at position 7 of 8: move the four-part residual contribution callout up to §1 as a "what's new" sidebar, with a forward pointer to §7's full neighborhood enumeration.
- **B2-4** conclusion punts the narrowed contribution: copy the four-part residual list verbatim into the conclusion (variable, DV, design, closed-model transfer).
- **B2-5** §5→§6 abrupt: add one-sentence bridge — "If closed models hide everything including the sycophancy directions, Phase 4's job is to read user-modeling state out of the visible output tokens. That motivates §6's introspection-as-readout discussion."

---

## Block 3 — Accessibility findings (load-bearing per methodology)

Rollup of the 10 sub-areas. All accepted; edits are gloss-insertion and example-insertion.

Highest-priority gloss rewrites (per the brief):

- **"residual stream"** — inline gloss at §1 first use: "the network's running internal scratchpad (technical term: 'residual stream' — see §4)."
- **"linear probe"** — inline gloss at §1 first use: "a small detector that learns to read one yes/no signal out of the scratchpad."
- **"fractional-factorial design" / "Resolution V"** — replace paragraph-long gloss with the reviewer's plain-English rewrite (five variables × 32 combinations → 16 specific combinations preserving main-effect and two-factor-interaction measurability).
- **"calibration" overloading two senses** — rename the §1 sense to "tune their effort" / "adjust their effort"; reserve "calibration" for §6's technical scale-conversion sense.

Other accepted accessibility edits:

- B3-1 remaining gloss insertions (interchange intervention, contrast pairs, causal mediation, factor analysis, benchmark, pretraining/post-training/fine-tuning distinction, benchmark-name index).
- B3-2 prior-art-dependency glosses (linear-probe-vs-non-linear-probe distinction; RepE/ActAdd/CAA interchangeability note; bar-restatement at §7).
- B3-3 unmotivated framings (rewrite §1 line 5 hook; add machine-cognition-sidestep half-sentence; reorder §4 evidence-grades table before methods table).
- B3-4 concrete examples (code-reviewer-vs-junior example for mechanism; CLAUDE.md example contents; one example prompt per fractional-factorial axis).
- B3-5 paragraph splits at §1 line 18, §4 line 187, §5 line 215 (the densest in the document), §7 line 293 (convert to bullets).
- B3-6 name-drop glosses (Shanahan, Geiger, Perez, Transluce, transformer-circuits.pub forward-move, NeurIPS-Spotlight equivalence, OLMo/Gemma).
- B3-7 insider quips (spell out the role-play-vs-identity stake; replace §7 line 305 hedge).
- B3-8 scale anchors ("monotone in model scale" → plain English; TruthfulQA 65% needs absolute-scale anchor; Ibrahim error rate needs "of what" specification).
- B3-9 DV/IV glossary; AuditBench gloss.
- B3-10 conclusion opening rewrite to a concrete take-away rather than abstract restatement.

No accessibility finding is rejected.

---

## Block 4 — Prose nits rollup

All eight sub-areas accepted as written. Edits applied as the reviewer specified:

- B4-1 topic-sentence rewrites at §1 line 53 and §4 line 169 (lead with claim, not citation).
- B4-2 bridge-sentence at §3 line 93→95; §5→§6 already covered under B2-5.
- B4-3 vary the §7 neighborhood-bullet rhythm (one-line summary leads, vary sentence count per bullet).
- B4-4 word-choice replacements ("a guess" → "something many practitioners have noticed"; "Standalone novelty" → "What Phase 1 contributes on its own"; "adopts" → "analyzes along").
- B4-5 hedge cuts (drop the redundant second sentence at §1 line 18; keep §7 line 295 offense-not-defense move; keep "partial" at §5 line 215).
- B4-6 modifier cuts ("enormous quantities" → "huge volumes"; "measurable accuracy changes" → "measured accuracy changes"; "tightly-related" → "related").
- B4-7 emphasis density (italicize "peer-ness" once, drop subsequent; keep bold in §4 table, drop in §4 prose).
- B4-8 corporate-speak (no changes — defensible as flagged).

---

## Edits checklist

Lit review edits (to apply against `/home/matt/claude-work/project-manager/pm/docs/literature-review-user-model.md`):

- [ ] §1: add training-data-imitation alternative-mechanisms paragraph (B1-1)
- [ ] §1: gloss residual-stream, linear-probe, contrast-pairs, factor-analysis, benchmark, DV/IV, pretraining-vs-post-training-vs-fine-tuning, benchmark-name index (B3-1, B3-9)
- [ ] §1: rewrite hook line 5; add machine-cognition sidestep clause; cut hedge at line 18 (B3-3, B4-5)
- [ ] §1: insert four-part residual contribution callout with forward pointer to §7 (B2-3)
- [ ] §1: split dense paragraph at line 18 (B3-5)
- [ ] §1: rename "calibration" first-sense to "tune their effort" (B3-1)
- [ ] §1: concrete code-reviewer-vs-junior example for mechanism (B3-4)
- [ ] §3: bridge sentence at line 95; CLAUDE.md contents example (B3-4, B4-2)
- [ ] §4: defer glossary to section end; gloss inline; reorder evidence-grades table before methods table; split Anthropic NLA paragraph (B2-1, B3-1, B3-3, B3-5)
- [ ] §4: add Non-Linear Representation Dilemma alongside Hernandez *only if citation verified* — otherwise skip (Step-5 verification)
- [ ] §4: gloss transformer-circuits.pub at first use; gloss Geiger; gloss Perez; gloss Transluce as research lab (B3-6)
- [ ] §5: add Lu et al. 2026 "Assistant Axis" to model-side-traits cluster (verified, parallel-axis peer)
- [ ] §5: soften Wang "partial pre-replication target" framing per B1-4 narrowing
- [ ] §5: split Wang paragraph at line 215 into three (B3-5)
- [ ] §5: scale anchor for Ibrahim error-rate (B3-8)
- [ ] §5→§6 bridge sentence (B2-5)
- [ ] §6: explicit consequence — Phase 4 is behavioral-grade only on closed models (B1-2)
- [ ] §7: add Lu et al. to neighborhood enumeration as model-side anchor
- [ ] §7: update alternative-mechanisms table cell with three disambiguation targets (B1-1)
- [ ] §7: factor-retention pre-commitment (parallel analysis) (B1-3)
- [ ] §7: family-wise error control sentence (B1-5)
- [ ] §7: rewrite fractional-factorial Resolution-V passage in plain English; vary bullet rhythm; bullet-ify residual-contribution paragraph; restate evidence-grade bars inline (B3-1, B3-2, B3-5, B4-3)
- [ ] §7: one example prompt per fractional-factorial axis (B3-4)
- [ ] §7: replace insider hedge at line 305 (B3-7)
- [ ] §8: move contamination passage forward to §1 / §7; reframe non-contaminated benchmark as primary DV (B1-6)
- [ ] Conclusion: rewrite opening to concrete take-away; copy four-part residual list verbatim (B2-4, B3-10)
- [ ] Document-wide: emphasis density audit (italics on "peer-ness" once; drop bold from §4 prose) (B4-7); word-choice swaps (B4-4); modifier cuts (B4-6); topic-sentence rewrites (B4-1)

Plan-side surfacing (separate change, not in this response cycle):

- [ ] plan-66d430f.md Phase 2: explicit primary-DV recommendation — non-contaminated recent benchmark (LiveBench / SWE-Bench Verified / BBH-extra), with MMLU/GSM8K/HumanEval demoted to secondary anchors interpreted as relative-movement signals under matched-content paraphrases (B1-6).
- [ ] plan-66d430f.md Phase 4: state that closed-model transfer is behavioral-grade only — verbalized readout calibrated to open-model probe, not a causal claim about closed-model representation (B1-2).
- [ ] plan-66d430f.md Phase 3: per-direction steering against independently-extracted register / status-rule / RLHF-policy directions as the explicit disambiguator vs. peer-ness (B1-1).
- [ ] plan-66d430f.md: family-wise error control note (B1-5).

---

## Verdict

This cycle's edits are predominantly internal-claim cleanup — accessibility gloss insertions, structural rebalancing, prose nits, and a small set of substantive Block-1 sharpenings (alternative mechanisms, Phase 4 evidence-bar, Wang construct-equivalence, contamination foregrounding). The Step-5 walk confirms the citation graph is approximately closed under current seeds; the one substantive addition (Lu 2026 Assistant Axis) is a parallel-axis peer that *complements* §5's model-side cluster rather than peer-ing with the plan's user-side IV. The contribution-narrowing principle does not apply this cycle. Per the reviewer's own framing: positive convergence signal.
