# Review Cycle 9 — User-Modeling as a Lever on LLM Performance

Blind adversarial review. Two artifacts:

- **Plan** — `pm/plans/plan-66d430f.md` ("User-Modeling as a Lever on LLM Performance")
- **Lit review** — `pm/docs/literature-review-user-model.md`

Priority of this cycle: the recently-added second hypothesis (H2 — sycophancy/corrigibility from a non-truth-seeking user-estimate) and its integration. H2 material is scrutinized hardest; the broader documents are still reviewed in full.

Word counts (whole-document verbosity pass, step 10):

- Plan: ~6,300 words (body, excluding PRs block ~2,400 → ~8,700 total).
- Lit review: ~11,400 words.
- Combined: ~20,100 words. **Flagged as too long** — see Block 2 finding B2-LR-1 and the verbosity pass at the end. Per methodology step 9, the response cycle for Cycle 9 must net-cut.

---

## Citation graph walk

### Seeds (listed before searching, per step 5a)

1. Choi, Huang, Schwettmann & Steinhardt 2025 — "Scalably Extracting Latent Representations of Users" (Transluce). The methodological peer for Phase 1.
2. Cabello & Neplenbroek 2025 — "Reading Between the Prompts" (EMNLP 2025). The probe+steer+output-effect peer.
3. Wang et al. 2026 — "When Truth Is Overridden" (AAAI 2026). The named H2 counterweight.
4. Sharma et al. 2023 — "Towards Understanding Sycophancy." The H2 RLHF backbone.
5. Fiske, Cuddy, Glick & Xu 2002 — Stereotype Content Model. The IV-structure anchor.
6. Vennemeyer et al. 2025 — "Sycophancy Is Not One Thing." The sycophancy-decomposition peer.
7. Chen et al. 2024 — "TalkTuner." The internal-user-model precedent for H2.
8. Tigges et al. 2023 — "Linear Representations of Sentiment." The closest single-axis methodological peer.

### Walk: dates covered, counts, findings

Forward and backward walk run on Google Scholar / WebSearch, date filter set to the last 12 months with emphasis on the last 6, searching beyond arXiv (ACL Anthology, OpenReview, dl.acm.org/CHI, transluce.org, alignment.anthropic.com).

**Material new prior art found — three items, two of them load-bearing against H2:**

1. **Verbalized Assumptions / "Verbalizing LLMs' Assumptions About the User to Calibrate Expectations and Reduce Sycophancy"** (CHI EA 2026, dl.acm.org/10.1145/3772363.3798611; full version arXiv:2604.03058, "Verbalizing LLMs' assumptions to explain and control sycophancy"). **This is the most serious miss in the document.** It is a near-exact methodological and conceptual preemption of H2. Verified from the abstract and the HTML full text:
   - It verbalizes and probes **nine user-assumption dimensions**, explicitly split into a sycophancy-increasing set (validation-seeking, user-rightness, user-information-advantage, emotional-support-seeking, companionship-seeking, belonging-support-seeking) and a sycophancy-decreasing set (**objectivity-seeking, information/guidance-seeking, tangible-support-seeking**).
   - "Objectivity-seeking" and "information/guidance-seeking" are H2's "truth-seeking" sub-dimension under different names — the user-internal estimate of whether the user wants the correct answer over reassurance.
   - It **trains 63 linear probes on LLM hidden states** (Llama-70B, Llama-8B; mean R² 0.64 / 0.50) to read out these assumption dimensions, then performs **probe-based steering** (`h_steered = h + α·v`) and measures **sycophancy as the DV**.
   - It reports that assumption-probe steering reduces social sycophancy **without sacrificing task performance**, and that it outperforms a direct sycophancy probe (which degraded quality) — a result that bears directly on the plan's Phase 3 sycophancy-direction comparison.
   - It frames the default failure as the model "underestimating how often users are seeking information over reassurance" — which is the plan's "RLHF biases the default user-estimate" claim, arrived at independently.

   This is not adjacent work; it is the same experiment H2 proposes (probe a user-truth-seeking/objectivity dimension → steer it → measure sycophancy), already run and published, on closed and open models, before this plan's H2 was added. **H2's contribution claim ("first to tie sycophancy to a probed user-model sub-dimension") is false as written and must be narrowed sharply.** See B1-PLAN-1 and B1-LR-1.

2. **"Mind Your Tone: Investigating How Prompt Politeness Affects LLM Accuracy"** (arXiv:2510.04950, Oct 2025) and the earlier **Yin et al., "Should We Respect LLMs? A Cross-Lingual Study on the Influence of Prompt Politeness on LLM Performance"** (arXiv:2402.14531; ACL SICON 2024). "Mind Your Tone" reports that **impolite** prompts *raised* GPT-4o accuracy by up to 4 points (80.8% very-polite → 84.8% very-rude). Yin et al. found the politeness→performance relationship is **non-monotone and model/language-dependent**. Politeness is one of the plan's five input axes (Methodology, line 163). This is contradicting empirical evidence for H1's directional prediction at the input-axis level and is not cited anywhere. See B1-PLAN-3 and B1-LR-2.

3. **Goodwin 2015, "Moral Character in Person Perception"** (Current Directions in Psychological Science 24(1):38–44) — an open-access author-hosted summary of Goodwin/Piazza/Rozin 2014. The lit review's reference list (line 439) flags Goodwin 2014 as paywalled with the characterization "based on standard secondary-source summaries." The 2015 Current Directions paper is the author's own summary, freely downloadable from web.sas.upenn.edu, and removes the need for the apologetic note. See B1-LR-7.

**Seeds that converged cleanly (no new material prior art):** Tigges 2023, Fiske 2002, Cabello & Neplenbroek 2025. The interpretability-tool cluster (Zou, Park, Arditi, Marks) is well-covered. Persona Vectors / Lu et al. Assistant Axis are current.

**Coverage statement:** the walk found three new items, one of which (Verbalized Assumptions, CHI 2026) is a direct preemption of H2 and the single most consequential finding of this cycle. This is *not* a clean convergence — the H2 material, being recently added, predates or did not search the CHI 2026 sycophancy literature, exactly the failure mode methodology step 5c warns about ("the most damaging misses in our loops have all been from the last 6 months").

---

## Block 1 — Substance

### B1-PLAN-1 / B1-LR-1 — H2's novelty claim does not survive Verbalized Assumptions (CHI 2026). LOAD-BEARING.

**Artifact:** Plan, "What is genuinely novel" line 233 ("First to tie sycophancy to a probed user-model sub-dimension — H2's truth-seeking probe — and test causally whether perceived truth-seeking drives sycophancy"); H2 "refined novelty" lines 30–32. Lit review §5 and §7.

The plan claims H2 is *first* to (a) probe a user-model sub-dimension that estimates user truth-seeking and (b) tie it to a sycophancy DV. Verbalized Assumptions (CHI 2026) did exactly this: it trained linear probes on hidden states for an "objectivity-seeking" / "information-seeking-vs-reassurance" user-assumption dimension, steered those probed directions, and measured sycophancy reduction. The "truth-seeking sub-dimension → sycophancy DV → probe → steer" pipeline is published prior art.

This is a narrow-don't-collapse situation (methodology p.134). The residual H2 contribution after Verbalized Assumptions:

- **What Verbalized Assumptions does:** verbalizes 9 user-assumption dimensions, probes them with linear probes, steers, measures *social* sycophancy (advice-seeking / over-validation) on advice-domain tasks. Its objectivity dimension is the closest analogue to H2's truth-seeking.
- **What H2 does that it doesn't:** (a) grounds the truth-seeking dimension in the SCM/peer-ness *meta-structure* rather than treating it as one of nine flat dimensions; (b) uses *gradable correctness benchmarks plus a corrigibility-under-pushback flip-rate* DV, not advice-domain social sycophancy; (c) escalates to **interchange-intervention** causal evidence (Verbalized Assumptions stops at steering — sufficiency-grade); (d) tests the truth-seeking estimate as a *joint function of input framing axes* rather than a directly-labeled dimension.

That residual is real but much smaller than "first to tie sycophancy to a probed user-model sub-dimension." **Required:** rewrite plan line 233 and the H2 "refined novelty" paragraph (lines 30–32) to the residual; add Verbalized Assumptions to the lit review §5 and the §7 neighborhood list and the references; and update the Predicted-outcomes H2 table interpretation rows, which currently read as if a positive H2 result would be a first.

Proposed replacement for plan line 233:
> - **Extends the probe-and-steer-the-user-truth-seeking-estimate result of Verbalized Assumptions (CHI 2026) from advice-domain social sycophancy to gradable-correctness benchmarks and a corrigibility-under-pushback DV, and escalates the causal bar from steering to interchange intervention.**

### B1-PLAN-2 — The RLHF causal-attribution nuance is *stated* correctly but a sentence later undercuts itself.

**Artifact:** Plan lines 32 and 221.

The careful claim — "H2 does **not** claim RLHF *causes* sycophancy outright — only that RLHF shifts where the model's default user-estimate sits" — is correct and well-drawn. But the very next sentences overreach: "Sycophancy then follows from the estimate, not from RLHF directly. That distinction is what makes the study informative: if sycophancy followed mechanically from RLHF there would be nothing to manipulate." This presents the estimate→sycophancy step as *settled*, when it is precisely what Phase 2/3 are supposed to test. The plan is assuming its own conclusion in the motivation. As written, a skeptical reader sees the plan claim "sycophancy follows from the estimate" in the H2 setup and then claim "H2 predicts X" in the DV section — the prediction has been smuggled in as a premise.

**Fix:** soften line 32 to "H2's *hypothesis* is that sycophancy follows from the estimate rather than from RLHF directly — which is what makes the study informative and falsifiable: if sycophancy followed mechanically from RLHF, there would be nothing to manipulate." One word ("hypothesis") and one verb mood change keeps the nuance honest.

### B1-PLAN-3 / B1-LR-2 — Contradicting evidence: politeness→performance is non-monotone and sometimes *negative*. Not cited.

**Artifact:** Plan Methodology line 163 (politeness is input axis 1); lit review §2.

The plan treats politeness as a peer-ness-loading input axis and H1 predicts higher peer-ness → better work. "Mind Your Tone" (arXiv:2510.04950) found impolite prompts *raised* GPT-4o accuracy by ~4 points; Yin et al. 2024 found the relationship non-monotone and model-dependent. The methodology's verbosity pass step 10 aside, this is a Block 1 substance gap: the plan has an input axis whose published main effect runs *opposite* to the hypothesized sign, and neither document mentions it.

This is not fatal — the plan's defense is available and is in fact stronger for being stated: politeness is *surface register*, deliberately separated from respect-for-competence precisely because the plan expects register and peer-ness to dissociate (this is confounder #1, register-matching). But the plan should say so explicitly and cite the contrary evidence. As written, a reviewer who knows "Mind Your Tone" reads the politeness axis as naive.

**Fix (lit review §2, one sentence):** "Two recent results complicate the naive 'be polite' story: 'Mind Your Tone' (arXiv:2510.04950, 2025) finds impolite prompts can *raise* GPT-4o accuracy, and Yin et al. (2024) find the politeness→performance curve non-monotone and model-dependent — which is exactly why the plan separates surface politeness from respect-for-competence and treats register-matching as a named alternative mechanism (§7)."

### B1-PLAN-4 / B1-LR-3 — Is the truth-seeking sub-dimension genuinely distinct from "reasonableness"? Under-argued.

**Artifact:** Plan H1 IV list line 16; H2 IV line 36.

The plan defines "reasonableness" as "does the user reason well, including about feedback?" and "truth-seeking" as "does the user value getting the correct answer over status and agreement?" These overlap heavily: a user who "reasons well about feedback" is, operationally, a user who updates toward correctness rather than defending status — which is the truth-seeking definition. The plan asserts truth-seeking is a distinct sub-dimension and even predicts (line 36) it will not need its own input axis because it is "activated by effort, honesty and respect-for-competence jointly." But if truth-seeking has no dedicated input axis and overlaps conceptually with reasonableness, the construct-validity story is thin: Phase 1's factor analysis could easily collapse truth-seeking and reasonableness into one direction, and the plan has no stated criterion for when that collapse falsifies H2 versus merely "revises the structure."

**Fix:** the plan needs an explicit discriminating operationalization. Reasonableness = quality of the user's *reasoning process* (do they argue validly, weigh evidence). Truth-seeking = the user's *goal* (do they want to be right vs. want to be agreed with). A user can reason well in service of winning an argument (high reasonableness, low truth-seeking) or reason sloppily but genuinely want correction (low reasonableness, high truth-seeking). Add one sentence making this orthogonality explicit, and add a Phase 1 acceptance sub-criterion: if truth-seeking and reasonableness probes correlate above some threshold (state it), report them as one dimension and treat H2 as testing that merged dimension. Right now the document leaves this as an unstated escape hatch.

### B1-LR-4 — Wang et al. "negligible expertise effect" handling: the rebuttal is asserted, not earned.

**Artifact:** Lit review §5 lines 245–249; plan line 223.

The lit review handles the Wang et al. counterweight by arguing Wang's "authority" probe loads on the SCM competence cell, so a Phase 1 null on intellectual competence would be "expected, not a surprise." This is a reasonable move, but it quietly concedes a lot: if Wang already shows the model does *not* internally encode user authority/competence, then the plan's *intellectual* peer-ness meta-axis — half the entire H1 construct — is predicted to come up empty before Phase 1 runs. The lit review treats this as a minor calibration note; it is actually a prediction that one of the two meta-axes will largely fail. The document should state plainly: "Wang's result predicts the intellectual-competence sub-dimension specifically may not be linearly decodable; if Phase 1 confirms this, the plan's live contribution narrows to the *moral* peer-ness axis plus effort and truth-seeking." That is a real concession the current text dodges with "expected outcome given Wang."

Also: Wang's finding that "user opinion statements reliably induce sycophancy" while expertise framing does not is itself relevant to H2 — it suggests the operative variable is the user *asserting a belief*, not the user's perceived stance. H2 should address whether its truth-seeking manipulation is distinguishable from "user states an opinion," since Wang shows opinion-statement is the dominant lever.

### B1-PLAN-5 — Phase 3 H2 acceptance criterion is weaker than the H1 criterion, undisclosed.

**Artifact:** Plan line 132 vs line 131.

Phase 3's H1 acceptance criterion is quantitative: "steering reproduces ≥50% of the framing-induced accuracy change." The H2 criterion (same line block) is only "produces a measured change in the sycophancy/corrigibility DV, reported with effect size and sign." "A measured change" is not a bar — any nonzero effect passes. Either H2 gets a parallel quantitative threshold (e.g., "reproduces ≥50% of the framing-induced sycophancy change") or the plan should state explicitly why H2's causal test is held to a lower bar. As written it reads as H2 having been bolted on without the same rigor pass H1 received.

### B1-LR-5 — "Persona Selection Model" (Marks/Lindsey/Olah 2026) cited as established mechanism; it is a recent hypothesis.

**Artifact:** Lit review §1 line 74.

PSM is presented as "names the post-training mechanism behind the plan's training-data-imitation story" — stated as if it is a settled account. PSM (alignment.anthropic.com, Feb 2026) is a three-month-old framework paper. The lit review elsewhere is careful to grade evidence (it grades Lindsey 2025 introspection as "suggestive," NLA as "not peer-reviewed but high-quality"). PSM gets no such hedge. Add one: "PSM is a recent (Feb 2026) framework rather than a settled result; the plan leans on it for vocabulary, not as load-bearing evidence."

### B1-PLAN-6 — The mechanism claim and the "RLHF-policy bypass" confounder are in tension, unaddressed.

**Artifact:** Plan "Mechanism" lines 20–22; Phase 3 alternative-mechanism #3 line 127; H2 RLHF discussion line 32.

The plan's H1 mechanism is *pretraining* imitation ("the plan's prediction follows directly from the training process"). Confounder #3 is an *RLHF-installed* policy that the plan wants to rule out. But H2's own backbone (line 32) says RLHF biases the default user-estimate — i.e., H2 explicitly *relies* on a post-training/RLHF effect. So the plan simultaneously (a) treats RLHF-policy as a confounder to be subtracted out in Phase 3 and (b) builds H2 on an RLHF-driven prior shift. These are not strictly contradictory (a prior-shift is not a policy), but the documents never reconcile them, and a careful reader will see Phase 3 trying to ablate the very mechanism H2 leans on. One paragraph is needed: distinguish "RLHF shifts a *prior over the user-estimate*" (H2's claim, the estimate is still the mediator) from "RLHF installs a *direct policy* user-sophistication→caution that bypasses the estimate" (confounder #3). They are different and the plan should say so where confounder #3 is defined, not leave the reader to notice.

### B1-LR-6 — Vennemeyer "Sycophancy Is Not One Thing" implies H2's single truth-seeking→sycophancy arrow is too coarse.

**Artifact:** Lit review §5 line 243; plan H2 DV line 37.

Vennemeyer shows sycophantic *agreement*, sycophantic *praise*, and genuine agreement are three separate directions. H2's DV (line 37) lumps "sycophancy rate and inappropriate corrigibility" as one DV with one predicted sign against one truth-seeking probe. If sycophancy is three things, H2's prediction "higher truth-seeking → lower sycophancy" may hold for agreement-sycophancy but not praise-sycophancy (which is more plausibly tied to moral peer-ness / warmth than to truth-seeking). The lit review notes Vennemeyer for Phase 1 probe-confusion but does not connect it to H2's DV design. H2 should commit to which of Vennemeyer's three components it predicts truth-seeking moves, or state that the DV is the agreement-component specifically.

### B1-PLAN-7 — "Each phase has independent scientific contribution" is asserted for H2 but Phase 1's H2 contribution is thin.

**Artifact:** Plan line 40 ("the only additions H2 requires are the truth-seeking probe ... and a sycophancy/corrigibility DV").

The plan says H2 adds independent value at each phase. But Phase 1's H2-specific contribution is just "extract one more probe by the same method" — and given Verbalized Assumptions already probed an objectivity/truth-seeking user dimension, Phase 1 alone delivers nothing new for H2. H2's earliest genuine contribution is Phase 3's interchange-intervention escalation. The plan should not claim per-phase independent H2 contribution; it should say H2's contribution lands at Phase 2 (the gradable-benchmark + corrigibility DV correlation) and Phase 3 (causal escalation), and Phase 1 simply folds the probe in.

---

## Block 2 — Structure and readability

### B2-LR-1 — The lit review is too long; ~11,400 words with heavy redundancy. LOAD-BEARING per step 9.

The §4 paper table plus §7's neighborhood list plus §4's closing "seminal anchors" paragraph plus the Conclusion's "where the plan inherits" bullet list all restate the same peer-comparison content four times. The four-part contribution claim is stated verbatim in §1 (line 29), §7 (lines 331–334), and the Conclusion (lines 403–406) — three identical copies. Keep one (the §7 version, where it is argued), replace the other two with a one-line cross-reference. Estimated saving: 600–900 words from de-duplicating the contribution claim and the anchor lists alone.

### B2-PLAN-1 — The plan repeats the sycophancy-as-competing-mechanism framing three times.

The "Sycophancy as a competing mechanism" content appears in confounder #1 (line 179), in the dedicated section (lines 237–245), and in H2 (lines 24–32). The dedicated section's lines 243–245 then re-explain the H2 refinement that lines 24–32 already explained. Collapse: keep the dedicated section as the single home, make confounder #1 a one-line pointer, and cut the H2 section's re-statement of the default-case/movable-estimate logic since the dedicated section covers it.

### B2-PLAN-2 — H2 is introduced before H1's variables are fully laid out, then re-introduced.

The "Hypotheses" preamble (lines 5–8) mentions H2 and "truth-seeking" before H1's IV is defined; then H1's IV list (line 16) defines truth-seeking again parenthetically as "the H2 sub-dimension"; then H2 gets its own section (lines 24–40). Truth-seeking is thus introduced three times before its hypothesis is stated. Tighten: define H1 fully, including truth-seeking as one sub-dimension with no forward reference, then introduce H2 once as "isolating the truth-seeking sub-dimension."

### B2-LR-2 — §5 abruptly switches register at the H2 refinement.

§5 opens in survey voice, then line 222–223 inserts "**H2 refines this**" as a meta-comment about an "earlier draft of this review." Telling the reader about the document's own revision history is an in-process artifact, not content (see also B3 and B4). The flow from "here is the sycophancy literature" to "here is what H2 claims" should be a clean topic transition, not a changelog.

### B2-PLAN-3 — Predicted-outcomes: H1 table and H2 table are separated by prose; consider merging or cross-locating.

The H1 predicted-outcome table (lines 199–204) and H2 table (lines 208–212) are good, but a reader scanning for "what happens if H2 fails" has to find a second table. Either merge into one table with an H1/H2 column, or put them adjacent with a single header.

---

## Block 3 — Non-expert accessibility (load-bearing)

### B3-LR-1 — "inverse scaling" used twice, glossed once but late.

**Artifact:** Lit review line 225 glosses it ("bigger models doing *worse*"); the plan uses "inverse scaling in RLHF" at line 221 with **no gloss**. The plan is a standalone artifact. Target reader does not know "inverse scaling."
**Fix (plan line 221):** "...identified it as a case of *inverse scaling in RLHF* — the counterintuitive pattern where more training makes the model *worse* at this, not better."

### B3-PLAN-1 — "corrigibility" / "inappropriate corrigibility" / "flip-under-pushback" used load-bearingly, never glossed in the plan.

**Artifact:** Plan lines 24, 26, 37, 38, 132, the DV PR. "Corrigibility" is research jargon; the target reader (a PM evaluating the tool) will not know it. The plan uses "flip-under-pushback" as if it were the gloss, but that phrase is itself opaque on first read.
**Fix (first use, line 24 area):** add one clause — "...inappropriate corrigibility — the model abandoning a correct answer when the user pushes back, even though the user is wrong (sometimes called caving under pushback)." Then "flip rate" later reads as "how often it caves."

### B3-PLAN-2 — "residual stream" used at line 36 and line 44 with no gloss in the plan.

The lit review glosses it ("the network's running internal scratchpad"); the plan never does. Plan line 44: "in the residual stream of an open base model." Target reader stops here.
**Fix:** first plan use → "in the residual stream (the network's running internal scratchpad — the sequence of internal states it builds up while processing the input)."

### B3-PLAN-3 — "Resolution V fractional-factorial design at 16 cells" — dense, unglossed, appears in the plan four times.

**Artifact:** Plan lines 52, 171, 173, the dataset PR. The lit review §7 explains it well ("picks 16 specific combinations that still let you measure each variable's effect on its own *and* whether any two interact ... same idea as A/B testing five UI changes at once"). The plan, a standalone artifact, never does.
**Fix (plan first use, line 52):** prepend one sentence — "Testing five on/off framing knobs would naively need 32 combinations; a *fractional-factorial design* picks a smaller subset — here 16 — that still measures each knob's own effect and every pair's interaction. 'Resolution V' is the name for the strength level that guarantees this." Then later uses can stay terse.

### B3-LR-2 — "interchange intervention" / "activation patching" — glossed in §4 but used in §1 of the lit review and all over the plan first.

The plan uses "interchange intervention / activation patching" at line 107 (Phase 3 heading) with the parenthetical but no actual explanation. A PM does not know what "patching" an activation means.
**Fix (plan Phase 3 goal, line 109):** "Steer each peer-ness direction independently — copy the internal state that encodes it from one model run into another, a technique called *activation patching* — and re-measure performance. Unlike merely adding a direction in, this isolates whether that state genuinely *causes* the behavior."

### B3-PLAN-4 — "SAE" / "Gemma Scope" / "TransformerLens / NNsight / SAELens" dropped in the plan with no gloss.

**Artifact:** Plan lines 48–49, 58, 217, 249, the tooling PR. These are named with URLs but no "what it is." A PM reading the plan sees five tool names in two sentences.
**Fix (line 48–49):** "...stand up the interpretability stack: TransformerLens and NNsight (libraries that let researchers read and edit a model's internal state), SAELens and Gemma Scope (a pre-built catalog of interpretable internal 'features' for the Gemma model). An *SAE*, or sparse autoencoder, is the tool that produces that catalog by decomposing the internal state into a list of single-concept features."

### B3-LR-3 — "Holm-Bonferroni / Benjamini-Hochberg FDR / family-wise error" — used in both documents, never glossed for a non-statistician.

**Artifact:** Plan lines 99, 175; lit review §7 line 311. The target reader (researcher in an adjacent field, PM) has ordinary literacy but may not know multiple-comparisons correction.
**Fix (first use, one clause):** "...apply family-wise error control — statistical corrections (Holm-Bonferroni, Benjamini-Hochberg) that compensate for the fact that testing many hypotheses at once inflates the chance of a false positive." Both documents can then use the bare names.

### B3-PLAN-5 — "Why should I care?" check fails for Phase 4's opening.

Phase 4 "Goal" (line 137) opens "Produce a calibrated output-token readout that elicits peer-ness self-reports from closed models." A PM does not know by the end of that sentence what they get. The benefit — "you can measure this on Claude/GPT/Gemini, the models you actually use in production, not just on research models" — is buried.
**Fix (Phase 4 goal):** lead with the benefit — "Make the peer-ness measurement usable on the closed models people actually deploy (Claude, GPT, Gemini), where the internal-probing tools of Phases 1–3 cannot reach, by having the model report its own judgment of the user and calibrating that report against the open-model probe."

### B3-LR-4 — "tool-to-agent gap" (AuditBench, §6 line 269) named without enough gloss.

The phrase is used as if self-explanatory. §6 says "tools effective in isolation don't reliably translate into investigator-agent effectiveness" — but "investigator-agent" is itself jargon.
**Fix:** "AuditBench documents a *tool-to-agent gap*: a measurement tool that works well when a researcher runs it directly often works far worse when an automated agent has to wield it. Phase 4 faces the same risk — the open-model probe may not survive being wrapped in a closed-model self-report prompt."

---

## Block 4 — Writing quality and prose craft

### B4-PLAN-1 — "At bottom this is one study" — vague opener.

**Before (line 5):** "At bottom this is one study: whether an LLM's internal read of the user as exhibiting **traditional intellectual and moral virtues** ... measurably changes the quality of the LLM's own work."
**After:** "This plan tests one question: does an LLM's internal read of the user — as competent, diligent, reasonable, truth-seeking, honest, and engaging in good faith — measurably change the quality of the LLM's own work?" ("At bottom" is deadwood; the colon-spliced 40-word sentence is hard to parse; the bold mid-sentence is emphasis clutter.)

### B4-PLAN-2 — "The documented sycophancy literature fits this framing rather than competing with it" — hedge-flavored and abstract.

**Before (line 32):** "The documented sycophancy literature fits this framing rather than competing with it."
**After:** "The existing sycophancy findings support H2 rather than undercutting it." (Cut "documented" — all literature is documented; "framing" is vague.)

### B4-LR-1 — Changelog prose embedded in the document. Recurring.

The lit review repeatedly narrates its own revision history: "An earlier draft of this review stated..." (line 223), "was missing from earlier drafts of this review" (line 203), "The earlier framing ... is walked back" (line 41). The plan does the same: "The earlier version of this plan had a Phase 4..." (line 302). A reader who never saw the earlier draft does not care. This is in-process scaffolding leaking into the artifact.
**Fix:** state the current position directly. **Before (line 203):** "...belongs in the same user-side-probing cluster and was missing from earlier drafts of this review. Chen et al. train..." **After:** "...belongs in the same user-side-probing cluster. Chen et al. train..." Apply the same cut to lines 41, 223, and plan line 302 (the Phase 4 history can be a one-line "Production integration is out of scope; see below" without the "the earlier version had").

### B4-PLAN-3 — Run-on with stacked clauses.

**Before (line 28):** "When the model reads the user as truth-seeking, it reproduces the pattern in which parties prioritize being right over deferring — even under the power asymmetry of the assistant relationship, where the user plainly has control the model does not."
**After:** "When the model reads the user as truth-seeking, it reproduces the pattern in which both parties prioritize being right over deferring. This holds even under the assistant relationship's power asymmetry, where the user has control the model does not."

### B4-LR-2 — Vague verb "fits."

**Before (line 56):** "Deas & McKeown, discussed in §4 and §7, establish SCM as an empirically-used framework on the LLM-probing side."
This one is fine. The offender is line 32 of the plan (handled in B4-PLAN-2) and line 217's "User-model-adjacent features exist" — a heading-like fragment as a bullet. **Fix:** "Sparse-autoencoder catalogs already contain user-model-adjacent features."

### B4-PLAN-4 — Emphasis density too high in the Hypotheses section.

Lines 5–40 contain bolded phrases at a rate of roughly one per two sentences ("**traditional intellectual and moral virtues**", "**H2 is a special case of H1**", "**H1 — peer-ness drives work quality**", "**IV**", "**DV**", "**The refined novelty**", "**What this says about RLHF**", "**not**", "**prior**"). When everything is bold nothing is. Keep bold for the H1/H2 hypothesis labels and the IV/DV labels; un-bold the rest, especially the mid-sentence "**not**" and "**prior**" which are doing drama, not signposting.

### B4-LR-3 — "non-trivial fraction" / "non-negligible fraction" — hedge that should be a number or cut.

**Before (line 225):** "human preference judgments themselves favor sycophantic responses over correct ones a non-trivial fraction of the time."
Sharma et al. give actual rates. Either cite the number or write "...favor sycophantic responses over correct ones often enough to bias the reward signal." "Non-trivial fraction" is a hedge pretending to be a measurement.

### B4-PLAN-5 — "At this time" deadwood.

**Before (line 287):** "No outstanding owner-attention items at this time."
**After:** "No outstanding owner-attention items." ("At this time" adds nothing — the whole document is a snapshot.)

### B4-LR-4 — Monotone sentence run in §2.

Lines 88–94 are a run of paper-summary paragraphs each opening "**[BoldName]** (citation) [verb]s...". EmotionPrompt / OPRO / Arvin / Salewski / Deshpande all follow the identical template. It reads as a catalog, not an argument. Vary at least two: lead one with the finding ("A 10-point accuracy swing from rewording a prompt — that is EmotionPrompt's headline...") and one with the contrast ("Where EmotionPrompt adds emotional stakes, OPRO adds none — just 'take a deep breath' — and still moves GSM8K 8 points.").

### B4-LR-5 — "leverage" / "lever" overused.

The title uses "Lever" (fine, it is the thesis metaphor). But §1, §2, §5 each independently call framing "a real lever" / "the plan's central guess" / "one such selector." Pick the lever metaphor and use it once per section maximum; the repeated "lever" dilutes the title's metaphor.

### B4-PLAN-6 — "plainly" and "unmistakably" — intensifiers doing argumentative work.

**Before (line 28):** "where the user plainly has control"; (line 32) "presenting an unmistakably truth-seeking user." "Plainly" and "unmistakably" assert agreement the reader has not given. Cut "plainly"; replace "unmistakably truth-seeking" with a concrete operationalization or just "a clearly truth-seeking user" — but better, point to the Phase 1 manipulation that defines "clearly."

---

## Verbosity pass (whole-document, step 10)

Counts: plan body ~6,300 words, lit review ~11,400. Combined with the PRs block, ~22,500 words. The lit review carries the most cuttable material:

- **Triplicated four-part contribution claim** (§1 line 29, §7 lines 331–334, Conclusion lines 403–406) — keep §7, cut two copies. ~250 words.
- **"Seminal anchors" trailing paragraphs** at the end of every section restate names already in the section body — these are navigational but redundant with the per-section "Why this section" openers and the references list. Either keep them or the "Why this section" lines, not both. ~400 words.
- **§4's evidence-grade material** (the salt-and-water worked example, lines 145; the three-grade list; the per-paper grade column) is excellent pedagogy but stated three ways — the table column, the prose list, and the worked example. Keep the worked example and the table column; cut the prose list. ~150 words.
- **Plan's "Sycophancy as a competing mechanism" section** duplicates H2 (B2-PLAN-1). ~300 words recoverable.
- **Changelog sentences** (B4-LR-1) — small individually, ~80 words total, all pure deadwood.

Verbosity pass is **not** a convergence signal this cycle — there is real cuttable redundancy (~1,200–1,500 words). The Cycle 9 response must net-cut per step 9, and the net cut should come from the de-duplication above, not from trimming H2 (H2 needs the Verbalized-Assumptions addition, which is a small net add — pay for it with the contribution-claim de-dup).

---

## Summary

**Finding counts:** Block 1 — 10 (B1-PLAN-1..7, B1-LR-1..7, several paired). Block 2 — 6. Block 3 — 9. Block 4 — 11 (plus the verbosity pass). Total ~36 distinct findings.

**Five most serious:**

1. **B1-PLAN-1 / B1-LR-1** — H2's "first to tie sycophancy to a probed user-model sub-dimension" novelty claim is preempted by Verbalized Assumptions (CHI 2026), which probed an objectivity/information-seeking user dimension, steered it, and measured sycophancy. H2's contribution must narrow to the residual (SCM meta-structure grounding, gradable-benchmark + corrigibility DV, interchange-intervention escalation).
2. **B1-PLAN-3 / B1-LR-2** — Contradicting evidence not cited: "Mind Your Tone" (2025) and Yin et al. (2024) show politeness→performance is non-monotone and sometimes negative; politeness is one of the plan's five input axes.
3. **B1-LR-4** — The Wang et al. handling quietly concedes that the entire intellectual-competence meta-axis may come up empty in Phase 1; the documents should state this concession plainly rather than frame it as "expected calibration."
4. **B1-PLAN-2 / B1-PLAN-6** — The RLHF causal nuance is stated correctly but then undercut by presenting "sycophancy follows from the estimate" as settled; and H2's reliance on an RLHF-driven prior shift is never reconciled with Phase 3 trying to ablate an RLHF-policy confounder.
5. **B1-PLAN-4** — Truth-seeking vs. reasonableness are not operationally distinguished; with no dedicated input axis for truth-seeking, Phase 1's factor analysis may collapse them and the plan has no stated falsification criterion for that case.

**Citation-walk outcome:** NOT clean convergence. Three new prior-art items found, one of them (Verbalized Assumptions, CHI 2026) a direct preemption of H2 — the single most consequential finding of the cycle and exactly the last-6-months miss the methodology warns about. The H1/interpretability core converged cleanly; the H2 material did not.

---

## Addendum — findings from Remote-Control discussion (post-blind-review)

These two findings did not come from the blind reviewer; they were surfaced in discussion after the cycle was saved, and are recorded here so the Cycle 9 response addresses them alongside the blind findings. Labeled separately to keep the blind-review audit trail honest.

### ADD-1 — Missing prior art and a sharper framing: truth-vs-approval and preference falsification. LOAD-BEARING.

**Artifact:** Lit review §5; plan H2 section and "Sycophancy as a competing mechanism."

Neither document names the human-scale analogue of LLM sycophancy, and naming it sharpens H2's mechanism. The load-bearing variable behind H2 is not peer-ness or politeness in the abstract — it is **whether the agent's feedback signal tracks truth or tracks a principal's approval.** Sycophancy is what a system does when its signal tracks approval. The tightest human-scale precedent is **Timur Kuran, *Private Truths, Public Lies: The Social Consequences of Preference Falsification* (Harvard University Press, 1995)**: agents under a power asymmetry misrepresent their private beliefs to match the perceived preferences of a power-holder, which corrupts the information the surrounding system runs on and stays invisible until it produces a discontinuous failure. LLM sycophancy *is* preference falsification performed by the model; H2's truth-seeking estimate is, precisely, the model's estimate of whether it is in a truth-tracking or an approval-tracking relationship. Because the H2 mechanism is training-data imitation, the model has compressed the human regularity Kuran described — which makes the LLM a measurable model-organism for it.

**Recommended (response cycle):** add Kuran 1995 to lit review §5 as the human-scale analogue (one to two sentences, terse — this is a net-cut cycle). Reframe the H2 mechanism statement around "truth-tracking vs. approval-tracking feedback" rather than leaving it implicit. Do **not** expand the plan with the broader civilizational argument (Hayek's knowledge problem, Scott's *Seeing Like a State*, historical informational-collapse cases) — that is significance framing, not experimental content, and this cycle must net-cut; at most a single "why this matters" sentence, or keep it out of the plan entirely.

### ADD-2 — Candidate additional sub-dimension: user intellectual humility.

**Artifact:** Plan IV list (H1, line 16); methodology input axes.

The IV currently carries four intellectual sub-dimensions (competence, effort, reasonableness, truth-seeking) and three moral ones (honesty, good faith, respect). A distinct candidate is missing: **the user's intellectual humility** — openness to being wrong, willingness to revise, calibrated rather than inflated confidence. The hypothesized effect is the mirror image of the sycophancy story: a user the model reads as intellectually humble may *license the model to take epistemic risks* — propose an uncertain answer, disagree, explore a non-obvious path — because a humble user will not punish a reasoned-but-wrong attempt. Humility is plausibly orthogonal to the existing sub-dimensions: it is not truth-seeking (a goal), not reasonableness (reasoning-process quality), and not competence (capability) — it concerns the user's relationship to their own fallibility.

**Recommended (response cycle):** the response's citation search should cover (a) the established intellectual-humility construct literature in psychology (it has validated scales) and (b) any LLM work probing or steering representations of user confidence/overconfidence. Then decide deliberately — do not reflexively expand scope — whether intellectual humility enters as a probed sub-dimension now or is recorded as a named follow-up axis. Given the cycle's net-cut obligation and the H2-preemption fallout, recording it as a scoped follow-up is the more likely correct call.
