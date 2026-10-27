# Review Cycle 10 — User-Modeling as a Lever on LLM Performance

Adversarial review of:
1. `pm/plans/plan-66d430f.md` — the research plan (9,787 words)
2. `pm/docs/literature-review-user-model.md` — the literature review (16,641 words)

Reviewer: fresh, blind to prior cycles. All four review blocks applied to both artifacts. Citation-graph walk and whole-document verbosity pass included.

---

## Summary up front

The artifacts are mature and internally far more consistent than a first-cycle artifact would be. Block 1 still surfaces real substance problems — the H2/H1 consistency story has a load-bearing crack, the Cheng et al. narrowing is honest but newly *under-credited* against just-published prior art the walk found, and one statistical-design claim is overstated. Blocks 2–4 are mostly convergence territory: the documents are well-organized and the prose is competent, with a finite list of specific fixes. Block 3 (accessibility) is the area with the most remaining work, because the lit review in particular has grown long enough that its glossing, while present, is buried.

Finding counts: Block 1 — 11; Block 2 — 7; Block 3 — 9; Block 4 — 8. Citation walk: **three pieces of new prior art from the last 4 months** that both documents miss, one of them directly preempting a Phase 3 claim.

---

## Block 1 — Substance

### B1-1 (plan + lit review) — The H2/H1 consistency story has a load-bearing crack: H2 is framed as "a special case of H1," but the *sign* of the mechanism is not the same.

Plan §"Hypotheses" line 7: "H2 is a special case of H1 — the same training-data-imitation mechanism, applied to a specific sub-dimension and a specific failure mode." H1's mechanism (line 22): humans calibrate *effort/care/rigor* to perceived peer-ness; the model imitates. H2's mechanism (line 28): truth-seeking discourse co-occurs with "correctness trumps status"; the model imitates *that*.

These are not the same regularity narrowed. H1 is a *quantity-of-effort* story (more peer → more careful work). H2 is a *conflict-resolution* story (more truth-seeking → correctness wins over deference when the two collide). A user can be perceived as a high-effort, highly competent peer (H1 high) and *also* be perceived as wanting flattery — a brilliant but vain collaborator. H1 predicts excellent work for that user; H2 predicts sycophancy. The two hypotheses are not nested; truth-seeking is a sub-dimension whose *effect direction on the DV is governed by a different mechanism* than the other five.

This matters because the plan repeatedly leans on the "special case" framing to justify folding H2 in cheaply ("H2 requires only two additions," line 40). If H2 is not actually a special case, then the claim that the same five input axes activate it (Methodology line 169: "the plan expects it to be activated jointly by the effort, honesty, and respect-for-competence axes") is a substantive empirical bet, not a definitional consequence.

**Fix.** Either (a) downgrade the framing from "special case of H1" to "a sibling hypothesis sharing the training-data-imitation *family* of mechanism but operating on a different regularity (conflict-resolution rather than effort-calibration)," and state plainly that H1 and H2 can dissociate — a user high on H1 can be low on H2; or (b) if the authors believe truth-seeking really is just effort-calibration applied to a sub-dimension, make that argument explicitly and defend it, because as written it is asserted, not argued. Option (a) is the honest one. The dissociation is itself an interesting predicted outcome and belongs in the Predicted-outcomes table as a row ("H1 high, H2 low for the same user-framing — vain-competent-user cell").

### B1-2 (plan + lit review) — NEW prior art the citation walk found: "Sycophancy Hides Linearly in the Attention Heads" (arXiv:2601.16644, Jan 23 2026) directly preempts part of Phase 3 and contradicts a Phase 1 methodological assumption.

Both documents assume the peer-ness and truth-seeking directions live primarily in the *residual stream* (plan Phase 1 "Goal," lit review §4 throughout). This paper trains linear probes across residual stream, MLP, and attention layers and finds that correct-to-incorrect sycophancy signals are *most* linearly separable in **multi-head attention activations**, and — load-bearing for the plan — that *steering is most effective in a sparse subset of middle-layer attention heads*, not the residual stream. It also reports that probes trained on TruthfulQA transfer to other factual-QA benchmarks (relevant to the plan's secondary-cross-check design).

This is closer to the plan's Phase 3 truth-seeking-steering experiment than Wang et al. 2026 (which the plan already treats as the counterweight). The plan's Phase 3 steering protocol (PR "Per-dimension steering protocol") injects at "one layer per dimension" in the residual stream. If the sycophancy signal is concentrated in attention heads, residual-stream steering may under-recover the effect and produce a false Phase 3 null.

**Fix.** Cite Genadi et al. 2026 in lit review §5 and §4's table. In the plan, Phase 3 ("Per-dimension steering protocol") and Phase 1 ("Extract and validate peer-ness vectors") must add attention-head-level extraction/steering as a candidate site, not commit to residual-stream-only. This is a concrete methodological correction, not a framing nicety.

### B1-3 (plan + lit review) — NEW prior art: "A Few Bad Neurons" (arXiv:2601.18939, Jan 26 2026) and "Mitigating Sycophancy via Sparse Activation Fusion" (OpenReview BCS7HHInC2, ICLR 2026) both preempt the H2 intervention story and should narrow the H2 contribution further.

"A Few Bad Neurons" uses SAEs + linear probes to isolate ~3% of MLP neurons most predictive of sycophancy and surgically corrects it — *on Gemma-2-2B and 9B*, the exact model class the plan's Tier 1 uses. The SAF/MLAS paper estimates and subtracts *user-induced bias* per-query in a sparse feature space and reports SycophancyEval QnA sycophancy dropping 63%→39% with accuracy doubling when the user is wrong.

The plan's H2 residual-contribution list (plan line 30) claims four unpreempted items: dispositional-attribute construct, gradable-correctness DV, interchange-intervention causal bar, closed-model calibration. The SAF paper's "per-query user-induced bias in sparse feature space" is *very close* to the per-query-intent vs. dispositional-attribute distinction the plan uses to differentiate itself from Cheng et al. — SAF explicitly does per-query estimation. This strengthens the plan's "we do disposition, they do per-query" line *against SAF* but also means the plan can no longer claim novelty for "isolating a user-side signal and steering it to reduce sycophancy on a gradable benchmark" in any general form — three independent groups now do versions of that.

**Fix.** Add both papers to lit review §5. Tighten the H2 residual-contribution claim (plan line 30 and lit review §5 Cheng paragraph) to foreground the *dispositional-attribute + Phase-1-tests-whether-it-is-stable* item as the genuinely distinctive one, because the gradable-DV and steering items are now multiply-preempted. This is "narrow, don't collapse" per methodology — the dispositional-stability test survives; the steering-on-gradable-benchmark item does not survive as novelty.

### B1-4 (plan) — The Cheng et al. narrowing is honest but the attribute-vs-intent distinction is asserted as if it were already established, when Phase 1 is supposed to *test* it.

Plan line 30: "H2's truth-seeking is a standing *attribute* of the user … in line with the rest of the plan's user-attribute IV." But the very same paragraph and Phase 1's acceptance criteria (line 73) admit Phase 1 must *check whether* the model represents it as a stable disposition "rather than collapsing it into per-message intent." So the contribution claim ("(a) it probes truth-seeking as a dispositional user attribute") presupposes the answer to a question the plan elsewhere flags as open.

This is a genuine logical circularity in the contribution statement. If Phase 1 finds the probe moves with per-message intent, then *by the plan's own line 73* "a probe that moves with per-message intent is measuring what Cheng et al. measure" — i.e., the H2 contribution collapses to zero in that branch.

**Fix.** Rewrite the contribution claim conditionally: "H2's *intended* construct is a dispositional attribute; Phase 1 tests whether the model in fact represents it that way. If it does, H2's contribution over Cheng et al. is [list]; if the probe tracks per-message intent instead, H2 reduces to a replication of Cheng et al. on a gradable DV, which is still a contribution but a smaller one." The plan should own that the contribution magnitude is *itself* a Phase 1 finding. Right now it is written as settled.

### B1-5 (lit review) — §5's "When Truth Is Overridden" treatment concedes the competence sub-dimension may be undecodable, but the plan does not propagate that concession.

Lit review §5 (Wang paragraph) makes a careful, honest concession: Wang's authority-probe null "predicts the intellectual-*competence* sub-dimension specifically may not be linearly decodable," and "if Phase 1 confirms this the plan's live contribution narrows to the moral peer-ness axis plus effort, reasonableness, and truth-seeking." That is good reviewing-against-self. But the *plan* (plan-66d430f.md) never mentions this. Plan Phase 1 lists competence as a first-class intellectual sub-dimension with no caveat; the "What is genuinely novel" section claims "first to probe peer-ness as a variable" without flagging that one of the six sub-dimensions has a published null against it.

**Fix.** Add one sentence to plan Phase 1 ("Extract and validate peer-ness vectors" or the Phase 1 prose): "Wang et al. 2026 report a null on internally encoded user *authority*, which overlaps the SCM competence cell; the competence sub-dimension is therefore the highest-risk probe, and a Phase 1 failure to decode it is an expected outcome rather than a defect." The lit review and plan must agree.

### B1-6 (plan) — The "Resolution V at 16 cells" claim for five 2-level factors is numerically wrong, or at best ambiguously stated.

Plan Methodology line 171 and Phase 1 line 52: "Resolution V fractional-factorial design at 16 cells." A 2^(5-1) design — 16 runs from five 2-level factors — is the *half-fraction* and it is **Resolution V** only for five factors: 2^(5-1)_V is indeed a standard Res V design. So 16 cells *is* correct for Res V at k=5. Good. But line 52 says "Testing five on/off framing knobs would naively need 32 combinations; a fractional-factorial design picks a smaller subset — here 16." For k=5, 2^(5-1)=16 is the half-fraction and it *is* Resolution V — fine. The genuine problem is the claim "all main effects and all two-factor interactions are estimable separately" combined with "higher-order interactions are aliased with main effects." In 2^(5-1)_V, main effects are aliased with **four-factor** interactions and two-factor interactions are aliased with **three-factor** interactions — main effects are *not* aliased with higher-order interactions in the sense the plan writes. Plan line 52 says "higher-order interactions are aliased with main effects" — that is the Resolution III description, not Resolution V. Methodology line 171 gets it right ("higher-order (three-way and above) interactions are aliased … higher-order interactions are aliased with main effects" — also wrong wording). The two passages contradict each other and at least one is incorrect.

**Fix.** State it precisely once: "In the 2^(5-1) Resolution V design, every main effect is aliased only with a four-factor interaction and every two-factor interaction only with a three-factor interaction; both classes of aliasing partner are assumed negligible. No main effect is aliased with another main effect or with a two-factor interaction." Then delete the "higher-order interactions are aliased with main effects" phrasing wherever it appears — it is the Res III property and is false here.

### B1-7 (plan + lit review) — The mechanism story's third claim ("LLMs reproduce the human pattern") is asserted, and the plan's own design cannot fully separate it from the named confounders.

Lit review §1 lines 66–72 honestly names the three alternative mechanisms (register-matching, high-status-interlocutor, RLHF-policy-bypass) and says Phase 3 disambiguates by steering independently-extracted confound directions. But extracting a clean "register" direction or a clean "RLHF-policy" direction by the *same contrast-pair method* (plan "Alternative-mechanism disambiguation" PR) assumes those confounds are themselves linearly separable and that the contrast pairs isolate them — the same assumption the plan flags as risky for peer-ness itself (plan "Open questions": "The mediator might not be a single direction"). If the confound directions are entangled with the peer-ness direction in the model's geometry, "steer the confound, see if peer-ness retains explanatory power" does not cleanly adjudicate. The plan treats confound-direction extraction as unproblematic while treating peer-ness-direction extraction as a named risk. That asymmetry is unjustified.

**Fix.** Add to the "Alternative-mechanism disambiguation" PR and lit review §7 a sentence acknowledging that the disambiguation is only as clean as the confound directions' own separability, and that a Phase 1 check (cross-correlation of the confound directions with the peer-ness directions) is a precondition for the Phase 3 disambiguation being interpretable.

### B1-8 (plan) — Phase 4's contribution claim ("First production-applicable peer-ness measurement for closed models") is overstated given Cheng et al.'s verbalized-assumption prompt is already a closed-model technique.

Plan Phase 4 "Standalone novelty" line 138 claims "First production-applicable peer-ness measurement for closed models." But the lit review §5 itself says Cheng et al.'s "verbalized-assumption prompt is itself a closed-model technique, validated on GPT-4o and Gemini; it is the natural Phase 4 baseline." So a closed-model verbalized readout of a user-side dimension already exists and runs in production. Phase 4's genuine residual is the *calibration against a probe-grounded scale* — the plan even says so in the same section. The "First production-applicable" phrasing oversells.

**Fix.** Change Phase 4's novelty line to: "First *probe-calibrated* peer-ness readout for closed models — Cheng et al.'s verbalized-assumption prompt already gives an uncalibrated closed-model user-dimension readout; Phase 4's contribution is tying the verbalized number to the open-model probe's scale so the closed-model self-report has known accuracy." This is the residual, stated honestly.

### B1-9 (lit review) — Goodwin et al. 2014 is cited as load-bearing (the three-factor alternative to SCM) but the reference note admits the abstract was inaccessible.

Reference list line 443: "Goodwin, Piazza & Rozin 2014 … (Abstract not directly accessible at the time of writing due to paywall; characterization based on standard secondary-source summaries.)" Goodwin is load-bearing — it is the *entire* basis for the "three-factor structure" branch of Phase 1's factor analysis and the predicted-outcomes table. Per methodology step 6, a paywalled work with no accessible version should either be verified through an open derivative or moved to a wanted-but-inaccessible appendix. The three-factor framing (morality + sociability + competence) is well-attested in secondary literature, so the *finding* survives, but the document should not lean this hard on a source it admits it could not read.

**Fix.** Goodwin's three-factor result is summarized in many open-access follow-ups (e.g., Brambilla & Leach; Goodwin's own later open work). Cite one open derivative alongside, or add an explicit one-line note in §1 that the three-factor structure is taken from secondary literature. Minimum: keep the honest note but add one verifiable open source.

### B1-10 (plan) — The "no hard thresholds, exploratory" stance is appropriate, but the Tier 1 → Tier 2 gate is now too vague to act on.

(Per the review brief, the absence of pass/fail thresholds is intentional and not a defect — agreed, not flagging that.) But plan Tier 1 (line 259) says "A clear positive — a probe that separates well above the noise floor on at least one sub-dimension, with steering that recovers a meaningful part of the framing delta — earns Tier 2. The … call is a judgment made on the reported results … the exact bar is set after Tier 1's exploratory results are in." That is fine as a *philosophy* but "well above the noise floor" and "a meaningful part" give a future operator nothing to hold. The methodology says: do not flag missing thresholds, but *do* flag what is too vague to act on. This is.

**Fix.** Not a numeric threshold — instead name the *decision procedure*: "The Tier 1 → Tier 2 call is made by [whom], comparing the best sub-dimension's probe separation against the Sclar 2024 paraphrase-noise floor computed on the same Tier 1 data; the gate is a written go/no-go memo, not a number, but it must cite the measured noise floor and the measured separation side by side." That makes the judgment auditable without pre-committing a threshold.

### B1-11 (lit review) — The Kuran / preference-falsification framing is elegant but is doing rhetorical, not load-bearing, work — and slightly overclaims.

Lit review §1 line 22 and §5 line 276 invoke Kuran's *preference falsification*: "Sycophancy, on this account, is not a training quirk but the model faithfully imitating preference falsification." This is a nice frame, but Kuran's concept is specifically about agents *concealing privately-held dissenting beliefs under social/political pressure* and the *cascade dynamics* that follow. LLM sycophancy as the plan models it is the model *inferring a non-truth-seeking user and adjusting* — there is no concealed private belief and no cascade. The analogy is evocative but the sentence "Sycophancy … is the model faithfully imitating preference falsification" asserts identity, not analogy.

**Fix.** Soften to analogy and make the mapping explicit: "Kuran's preference falsification is the human-scale *analogue*: just as people misrepresent private belief to a power-holder, an LLM that reads its user as approval-seeking suppresses the answer it would otherwise give. The plan does not claim the LLM has a concealed private belief — only that the input-output regularity rhymes." Keep the frame; drop the identity claim.

---

## Block 2 — Structure and readability

### B2-1 (lit review) — §4 is far too long and is the document's structural bottleneck.

§4 runs from line 124 to ~233 — roughly 5,000 words, nearly a third of the lit review. It contains: a 14-item glossary, two large tables, an evidence-grade tutorial with a salt-water worked example, an experimental-styles table, and ~15 paper paragraphs. A reader arriving at §4 to find out "how does the plan read the variable out" must wade through all of it. This is the single biggest "reader closes the tab" risk in either document.

**Fix.** Split §4 into §4a "The interpretability toolkit" (the glossary, the three-evidence-grades explainer, the experimental-styles table — the conceptual scaffolding) and §4b "The prior-art catalogue" (the paper-by-paper walk and the second table). Move the salt-water worked example to a footnote or call-out box. A reader who already knows what activation patching is can skip §4b entirely; a reader who doesn't needs §4a only.

### B2-2 (lit review) — The §1 glossary is in the wrong place and split awkwardly.

§1 (lines 33–48) contains a long glossary block, then says "the more technical interpretability terms are glossed inline in §4." So there are two glossaries in two sections. A reader hits a wall of definitions four paragraphs into the Introduction.

**Fix.** Move the entire glossary to a single "Glossary" section immediately after the Introduction (or an appendix referenced from the top), and have §1 contain at most three or four inline glosses for the terms it *actually uses* before the glossary appears. The Introduction should read as prose, not as prose interrupted by a dictionary.

### B2-3 (plan) — The "Hypotheses" section front-loads the H2/Cheng-et-al. narrowing before the reader knows what H2 even is.

Plan lines 24–40: the H2 statement (line 26) is immediately followed by a dense "refined contribution — what is new after Cheng et al. 2026" paragraph (line 30) and a "What this says about RLHF" paragraph (line 32) before the reader has seen H2's variables (lines 34–38). The reader is asked to evaluate a contribution-narrowing against a paper they have not been introduced to, before they have the hypothesis's own variables.

**Fix.** Reorder: H2 statement → H2's two variables → predicted sign → *then* the Cheng et al. narrowing and the RLHF discussion. Contribution-narrowing is third-order content; it should not interrupt the first-order definition.

### B2-4 (plan + lit review) — The sycophancy material is spread across too many locations and partly repeats.

In the plan, sycophancy is discussed in: H2 (lines 24–40), "What the literature already establishes" (line 218), "Sycophancy as a competing mechanism" (lines 234–240), Predicted outcomes, and several PRs. The "Sycophancy as a competing mechanism" section and the H2 section restate the IV-vs-behavior / perception-vs-flattering point three times in near-identical words ("The IV in both cases is the model's *perception* … not the *behavior*").

**Fix.** State the perception-vs-behavior distinction once, in the H2 section, and have "Sycophancy as a competing mechanism" cross-reference it rather than re-explain it. The section can shrink by roughly half.

### B2-5 (lit review) — The two big tables in §4 overlap and should be merged or differentiated.

The "experimental styles" table (lines 150–161) and the "papers catalogued" table (lines 166–186) both list papers and both have an evidence-grade column. A reader cannot tell at a glance why there are two tables or which to consult.

**Fix.** Either merge into one table (paper × style × evidence-grade × open-weights-needed × role-for-plan) or add a one-line header to each saying what question it answers ("Table A: what kinds of experiment exist. Table B: which paper does which, and what it gives the plan").

### B2-6 (plan) — "What the literature already establishes" and "What is genuinely novel about this plan" duplicate the lit review's job.

The plan carries a ~10-bullet literature summary (lines 212–221) and a novelty list (lines 224–232). The lit review exists precisely to do this. The plan's version will drift out of sync with the lit review (and already has — see B1-5, the Wang competence concession is in the lit review but not the plan).

**Fix.** Cut the plan's "What the literature already establishes" to three or four sentences and point to the lit review for the rest. Keep the novelty list in the plan (it is plan-scoped) but ensure it is the *same* residual-contribution wording as lit review §7.

### B2-7 (both) — Good convergence: section-to-section flow and "Why this section" openers.

Positive finding. The lit review's "*Why this section*" italic openers are genuinely effective — they pass the "why should I care" check, and the section ordering (background → framing effects → scaffolds → steering toolkit → sycophancy → introspection → novelty → benchmarks) is logical. The plan's phase structure and PR dependency graph are clean. No structural rework needed beyond the above; this axis has largely converged.

---

## Block 3 — Non-expert accessibility (load-bearing)

The target reader: a PM or adjacent-field researcher evaluating the work, ordinary technical literacy, no ML-research vocabulary. Both documents have clearly had accessibility passes — there are inline glosses, "in plain English" recaps, scale anchors. The problem now is not absence of glossing but that the glossing is *buried under volume* and a few load-bearing terms still slip through.

### B3-1 (plan) — The plan has had almost no accessibility pass; it is far less accessible than the lit review.

The lit review glosses "residual stream," "linear probe," "RLHF," etc. The plan uses all of these load-bearingly and glosses only some. Plan line 49 glosses SAE and Gemma Scope well. But plan Phase 1 line 44 uses "linearly-decodable" with no gloss; line 46 uses "RepE," "mean-diff," "contrast-pair" with no gloss; line 49 "TransformerLens … NNsight" gets a gloss but "SAELens" does not; Phase 3 line 109 glosses activation patching well but line 114 "fixed probe magnitude" is unglossed. The plan is a standalone artifact (it has its own "Why this fits in pm" section aimed at pm users) and cannot assume the reader has read the lit review.

**Fix.** The plan needs a short glossary block of its own, OR a one-line pointer at the top: "This plan uses interpretability terms (probe, residual stream, steering, activation patching) defined in `literature-review-user-model.md` §4 — read that first if they are unfamiliar." The pointer is the cheaper fix and is honest about the dependency. Without it, the plan fails the accessibility bar for its stated pm-user audience.

### B3-2 (lit review) — "interchange intervention" is glossed but the gloss itself is hard.

§4 line 137 glosses activation patching / interchange intervention: "Run the network twice with two different inputs; copy the network's internal state from one run into the same position of the second run; then check whether the second run's answer changes the way you expected." This is correct but the target reader does not know what "position" means or why copying internal state proves causation.

**Proposed rewrite:** "Interchange intervention is the strongest test that an internal signal *causes* a behavior, not just accompanies it. You run the model on input A and on input B. You then take one specific piece of the model's internal state from the A-run and paste it into the B-run, leaving everything else in B untouched. If B's answer now shifts toward what A would have produced, that pasted piece was doing real causal work — like swapping one ingredient between two recipes and seeing the dish change." (This reuses the salt-water frame the document already has, so no new jargon.)

### B3-3 (lit review) — "fractional-factorial" / "Resolution V" / "aliasing" are glossed three separate times and still land as jargon.

The terms are explained in plan line 52, plan Methodology line 171, and lit review §7 lines 314–326. Three explanations, and the §7 one is the clearest. The target reader meets "Resolution V fractional-factorial" in §1's Phase summary (line 27) long before §7's explanation.

**Fix.** On *first* mention (lit review §1, plan Phase summary), use only the plain-English version and defer the term: "a carefully chosen set of 16 prompt variations that lets every framing knob's effect be measured separately (the statistical name, *Resolution V fractional-factorial design*, and why 16 is the right number, are in §7)." Then explain once, in §7, and nowhere else. Currently the term is used before it is defined and defined three times.

### B3-4 (lit review) — "model-graded evaluation" / "LLM-as-judge" appears in §4's experimental-styles prose (line 162) with a gloss that assumes the reader knows what a "fine-tuned classifier" is.

Line 162: "*model-graded evaluation* (an LLM-as-judge or fine-tuned classifier scores an open-ended dependent variable)." "Fine-tuned classifier" is unglossed jargon.

**Proposed rewrite:** "*model-graded evaluation* — when the thing being measured is not a simple right/wrong answer (e.g. 'how sycophantic was this reply?'), a second AI model is used as the grader, scoring each response the way a human rater would."

### B3-5 (plan) — "INPUT_REQUIRED" appears in two PRs ("Choose open base + tooling," "Transfer to closed models") with no gloss.

Plan line 304 and line 424: "the review loop should use INPUT_REQUIRED if it cannot load the model." This is a pm-internal harness token. A pm user evaluating the plan does not know what it means.

**Fix.** Gloss on first use: "use INPUT_REQUIRED (pm's signal that an automated run must pause and ask a human) if …".

### B3-6 (lit review) — "tool-to-agent gap" in §6 (line 290) is named as if the reader knows the concept.

Line 290: "AuditBench documents a *tool-to-agent gap*: a measurement tool that works well when a researcher runs it directly often works far worse when an automated agent has to wield it." The gloss is actually present and good — but the term is then *used again* without the reader having a concrete picture of what an "automated agent wielding a tool" looks like.

**Proposed addition (one example sentence):** "Concretely: a probe that a researcher tunes by hand and inspects may break when it is dropped into an automated pipeline that runs it unattended across thousands of prompts — the same gap Phase 4 risks when the open-model probe gets wrapped inside a closed-model self-report prompt."

### B3-7 (plan) — "Owner-attention items" section assumes the reader knows what that means.

Plan line 282: "No outstanding owner-attention items." This is a pm-plan-format heading. A reader outside pm does not know "owner-attention" is pm's term for decisions the human owner must make.

**Fix.** Either rename the heading to "Decisions the project owner must make" or gloss it: "**Owner-attention items** (decisions that need a human call before or during the run)."

### B3-8 (lit review) — "Spotlight," "Findings of EMNLP," "Main" are conference-process jargon, glossed once but used widely.

Line 46 glosses "NeurIPS *Spotlight*." But "Findings of EMNLP" (used ~6 times) is never glossed — "Findings" is a specific second-tier acceptance track and a non-academic reader will read it as the title of a journal.

**Fix.** One-line gloss at first use of "Findings of EMNLP": "(*Findings* is a peer-reviewed companion track to the main conference — fully refereed, slightly lower selectivity)."

### B3-9 (both) — Positive convergence: scale anchors and "in plain English" recaps are well done.

Genuine positive. The lit review consistently anchors numbers ("a 10-point shift from rewording is large … switching GPT-3.5→GPT-4 is 15–20 points"; "an A to an F from changing whitespace"). The Phase summaries' "*In plain English*" recaps (§1 lines 26–29) are exactly the right move. This axis has largely converged in the lit review. The plan, by contrast, has *none* of this and should borrow the technique for at least the Hypotheses and Phase 1 sections (see B3-1).

---

## Block 4 — Writing quality and prose craft

### B4-1 (plan) — Line 22, run-on with stacked clauses.

Current: "In that corpus, humans calibrate effort, care, and rigor based on the perceived equality of their partner: experts write more carefully for other experts; people argue more rigorously with collaborators they respect; sloppy interlocutors elicit sloppy replies."

The colon-then-three-semicolon-list is fine, but the sentence before it and after it both also pile clauses. The whole paragraph (line 22) is one 9-line block.

**Rewrite (split):** "In that corpus, humans calibrate effort to the perceived equality of their partner. Experts write more carefully for other experts; people argue more rigorously with collaborators they respect; sloppy questions get sloppy replies. LLMs internalize this calibration as a pattern. The plan's prediction follows directly: if the model has read the pattern, it reproduces it."

### B4-2 (lit review) — §1 line 22, "on a darker regularity" is doing dramatic work the sentence cannot pay off cleanly.

Current: "The same argument runs a second time, on a darker regularity, and produces the plan's second hypothesis (H2)."

"Darker regularity" is a flourish; the reader does not yet know what is dark about it.

**Rewrite:** "The same argument applies a second time to a less flattering human regularity, and produces the plan's second hypothesis (H2): people also learn to tell power-holders what they want to hear."

### B4-3 (plan) — Hedge-stacking in the H2 RLHF paragraph (line 32).

Current: "RLHF on that data plausibly biases the model's *prior* over users: it learns a user *can* be truth-seeking but by default probably is not."

"Plausibly … probably" stack two hedges on one claim. One is enough.

**Rewrite:** "RLHF on that data plausibly biases the model's *prior* over users: it learns that a user *can* be truth-seeking but defaults to assuming otherwise."

### B4-4 (lit review) — §4 line 142, the three-distinctions sentence buries its load-bearing clause.

Current: "The plan's Phase 2 needs only behavioral-grade evidence (probe + benchmark); Phase 3, which claims causation of one direction on performance, needs interchange-intervention-grade evidence — *steering alone is sufficiency-only and does not clear the mediation bar*."

The most important clause ("steering alone does not clear the bar") is appended after a dash as an afterthought.

**Rewrite:** "Phase 2 needs only behavioral-grade evidence — a probe plus a benchmark score. Phase 3 claims one direction *causes* the performance change, and that claim needs the strongest standard: interchange intervention. Steering alone is not enough; it shows a direction is *sufficient* to move behavior, not that the model *uses* it."

### B4-5 (lit review) — Word choice: "leverage"/"levers" overused as a metaphor.

The word "lever" / "leverage" appears in the title, §1, §2 ("framing is a real lever"), §5, §6. It is the document's controlling metaphor and by repetition it has gone flat.

**Fix.** Keep it in the title (it earns its place there). In the body, vary: "framing is a real lever" → "framing genuinely moves accuracy"; "a different lever" (§3 line 120) → "a different mechanism." Cut the count by at least half.

### B4-6 (plan) — "load-bearing" is itself overused.

The plan uses "load-bearing" for: variables (line 13), the H1 weakest link, the measurement risk. The lit review uses it ~8 times. It is reviewer/engineer jargon that has crept into the artifact's own voice.

**Fix.** Replace with the specific thing meant each time: "H1 has two load-bearing variables" → "H1 turns on two variables"; "one measurement risk is load-bearing enough to flag here" → "one measurement risk is serious enough to flag here."

### B4-7 (lit review) — §5 line 240, a 5-line sentence-paragraph that should be three sentences.

Current (the "H2 sharpens this" paragraph) packs: the downstream-of-representation claim, the default-case caveat, the Sharma evidence, the RLHF-prior claim, and the movable-estimate bet into one breathless run.

**Rewrite (split into three):** "H2's claim is that sycophancy is downstream of one specific sub-dimension of the user-representation — the model's estimate of how truth-seeking the user is. The model carries that estimate, and it is what licenses the model's own truth-seeking; sycophancy is what happens when the estimate is low. The 'sycophancy is separable from the user-representation' framing holds only for the default case: RLHF preference data favors agreement even when the model is wrong (Sharma et al.), so RLHF plausibly biases the model's prior toward assuming users are not truth-seeking. H2's bet is that this estimate is movable — present a clearly truth-seeking user and sycophancy should fall."

### B4-8 (both) — Emphasis density: italics are overused and cancel out.

Both documents italicize heavily — §5 line 240 alone italicizes "downstream of," "default case," "prior," "movable." When four phrases per paragraph are italic, none of them stand out. The plan's Hypotheses section italicizes the hypothesis statements (correct — block quotes earn it) but then also italicizes scattered words throughout.

**Fix.** Reserve italics for (a) the formal hypothesis statements and (b) genuine first-use term introductions. Cut italic emphasis on ordinary words ("really," "used," "present"). Target: no more than one or two italic spans per paragraph.

---

## Citation graph walk

### Seeds (8, chosen as the most load-bearing references)

1. Choi, Huang, Schwettmann & Steinhardt 2025 — "Scalably Extracting Latent Representations of Users" (Transluce) — Phase 1 methodological peer.
2. Cheng et al. 2026 — "Verbalizing LLMs' Assumptions About the User" (CHI EA 2026) — the H2 preempting paper.
3. Wang et al. 2026 — "When Truth Is Overridden" (AAAI 2026) — the named sycophancy counterweight.
4. Cabello & Neplenbroek 2025 — "Reading Between the Prompts" (EMNLP 2025) — closest pipeline peer.
5. Deas & McKeown 2025 — "Artificial Impressions" (EMNLP 2025) — SCM-linear-probe peer.
6. Rimsky et al. 2024 — "Contrastive Activation Addition" — the steering method.
7. Fiske/Cuddy/Glick/Xu 2002 — Stereotype Content Model — the IV-structure anchor.
8. Vennemeyer et al. 2025 — "Sycophancy Is Not One Thing" — sycophancy-decomposition peer.

### Walk

Forward/backward search via WebSearch, date-filtered to the last ~6 months, across arXiv, OpenReview, dl.acm.org (CHI/AAAI proceedings), and lab pages. Coverage:

- **Seed 2 (Cheng et al.) forward walk** — surfaced the CHI 2026 sycophancy cluster: "Be Friendly, Not Friends: How LLM Sycophancy Shapes User Trust" (CHI 2026, dl.acm.org/10.1145/3772318.3791079). Adjacent (it studies *user trust* as the DV, not internal representations) — **not** a missing peer, but worth a one-line mention in §5 as evidence the sycophancy-and-user-perception space is active at CHI.
- **Seed 3 (Wang et al.) forward walk** — surfaced three new mechanistic-sycophancy papers from Jan 2026, all missed by both documents:
  - **"Sycophancy Hides Linearly in the Attention Heads" (arXiv:2601.16644, Jan 23 2026)** — NEW, load-bearing. See B1-2. Finds sycophancy signal is most separable in *attention heads*, steering most effective in middle-layer attention, not the residual stream. Directly bears on Phase 1 extraction site and Phase 3 steering site.
  - **"A Few Bad Neurons: Isolating and Surgically Correcting Sycophancy" (arXiv:2601.18939, Jan 26 2026)** — NEW. See B1-3. SAE + linear probe isolates ~3% of MLP neurons; tested on Gemma-2-2B/9B (the plan's exact Tier 1 models). Preempts part of the H2 intervention novelty.
  - **"Mitigating Sycophancy via Sparse Activation Fusion and Multi-Layer Activation Steering" (OpenReview BCS7HHInC2, ICLR 2026)** — NEW. See B1-3. Per-query user-induced-bias subtraction in sparse feature space; bears on the H2 per-query-vs-disposition distinction and on Phase 3's sycophancy-direction comparison.
- **Seed 7 (SCM) forward walk** — surfaced an SCM-based LLM bias-evaluation framework (Word Association Bias Test / Affective Attribution Test) reconceptualizing bias as a three-dimensional ToM failure (Competence, Sociability, Morality) — this is *additional support* for the plan's "factor analysis may find three factors" branch and could be cited in §1 alongside Goodwin. Minor; optional addition.
- **Seeds 1, 4, 5, 6, 8** — forward/backward walks surfaced no new closer peers than the documents already cite. Choi/Transluce, Cabello, Deas & McKeown, Rimsky, Vennemexer coverage is current as of the documents' draft date. This is a convergence signal on the *variable-side* peer set.
- **"Linear Probe Accuracy Scales with Model Size and Benefits from Multi-Layer Ensembling" (arXiv:2604.13386)** — surfaced near the sycophancy cluster; supports the plan's Tier 2 "multi-layer ensemble probes" choice. Optional supporting citation for the Infrastructure / Tier 2 section.

### Walk outcome

**Not a clean convergence.** The variable-side peer set (Choi, Cabello, Deas & McKeown, TalkTuner, Cheng) is current and well-covered — that part has converged. But the *mechanistic-sycophancy* literature moved fast in January 2026, after the documents' last substantive revision, and three new papers (2601.16644, 2601.18939, OpenReview BCS7HHInC2) are now closer to Phase 3 / H2 than some papers the documents do cite. The most serious is **2601.16644**, which contradicts the documents' working assumption that the relevant signal lives in the residual stream — a methodological correction, not just a citation add.

---

## Whole-document verbosity pass

Word counts: plan **9,787 words**; lit review **16,641 words**; combined **26,428**.

The lit review is long for its job. §4 alone is ~5,000 words (B2-1). Specific cuts identified, beyond the structural split in B2-1:

- **Lit review §4 evidence-grade tutorial** — the salt-water worked example (line 144) is repeated in essence at line 137 and again as the three-grades list. The salt-water analogy is good; keep it *once*, cut the redundant inline restatement at line 137.
- **Plan "Sycophancy as a competing mechanism"** (lines 234–240) — restates the perception-vs-behavior distinction three times (B2-4). Cuttable to ~half: ~250 words saved.
- **Plan "What the literature already establishes"** (lines 212–221) — duplicates the lit review (B2-6). Cuttable from ~10 bullets to 3–4 sentences: ~400 words saved.
- **Lit review §5 Wang paragraph** (lines 262–266) — three paragraphs on Wang where two would do; the "precise reading" paragraph (266) repeats the SCM-competence-cell point made in 262–264.
- **Lit review §7 "What the plan is and isn't claiming"** — the neighborhood enumeration (lines 338–346) and the residual-contribution list (350–357) partly restate §4's table content. The bullets each carry a "Same: … Different: …" structure that is good, but several ("LLM-own-behavior features," "The model's own Assistant persona") repeat §4 and §5 verbatim in compressed form.
- **Hedge/deadwood sweep** — "it should be noted," "in many cases," "plausibly … probably" stacks (B4-3), and the "load-bearing" tic (B4-6) recur throughout. A mechanical sweep would remove ~300–400 words across both documents.

**This pass found real cuttable material — it is not a convergence signal.** Estimated achievable reduction without losing any point: ~1,500–2,000 words combined (roughly 7%), concentrated in plan §"What the literature already establishes," plan §"Sycophancy as a competing mechanism," and lit review §4/§5/§7 restatements. Per methodology step 9, since length is hereby flagged, the response cycle must net-cut: every new citation from the walk (three papers) goes in as one terse sentence each, paired with a larger cut elsewhere.

---

## The five most serious findings

1. **B1-1** — H2 is framed as "a special case of H1" but the mechanisms differ in kind (effort-calibration vs. conflict-resolution); H1 and H2 can dissociate for the same user. The "special case" framing is used to justify folding H2 in cheaply, and that justification does not hold. Downgrade to "sibling hypothesis, shared mechanism family."

2. **B1-2** — NEW prior art "Sycophancy Hides Linearly in the Attention Heads" (arXiv:2601.16644, Jan 2026) finds the sycophancy signal is most separable in attention heads and steering most effective in middle-layer attention — not the residual stream, where both documents assume it lives. This is a methodological correction to Phase 1 extraction and Phase 3 steering, not just a citation gap.

3. **B1-4** — The H2 contribution claim ("probes truth-seeking as a dispositional attribute") presupposes the answer to a question Phase 1 is supposed to *test*. By the plan's own Phase 1 acceptance criteria, if the probe tracks per-message intent the H2 contribution collapses to a Cheng et al. replication. The contribution statement must be made conditional on the Phase 1 result.

4. **B1-3** — Two more NEW Jan-2026 papers ("A Few Bad Neurons"; SAF/MLAS, OpenReview) independently do user-side-signal isolation + sycophancy reduction on gradable benchmarks, on Gemma-2-9B specifically. The H2 residual-contribution list must narrow: the dispositional-stability test survives as novelty; "steer a user-side signal to cut sycophancy on a gradable DV" no longer does.

5. **B1-6 / B2-1** — Tie: the "Resolution V" aliasing claim is stated incorrectly in two places (the "higher-order interactions aliased with main effects" phrasing is the Resolution III property, false for 2^(5-1)_V) and the two passages contradict each other; and lit review §4 (~5,000 words, a third of the document) is the structural bottleneck most likely to make a reader stop.

---

## Convergence assessment

Per methodology step 8: the artifacts have genuinely converged on **structure-to-structure flow** (B2-7), **scale anchors and plain-English recaps in the lit review** (B3-9), and the **variable-side peer set** (citation walk — Choi/Cabello/Deas/TalkTuner coverage is current). Block 2 and the lit-review half of Block 3 are near their natural stopping point; the Block 4 findings are mostly phrasing-level and several border on pedantic.

Block 1 is **not** converged: B1-1 (H2/H1 consistency) is a genuine conceptual problem, and the citation walk found three new papers from after the last revision, one of which (B1-2) forces a methodological change. The plan-vs-lit-review consistency gap (B1-5: the Wang competence concession lives only in the lit review) is the kind of drift the methodology warns about. This cycle produced 35 findings — more substance findings than a converged artifact should, driven mostly by the H2 material and the fast-moving Jan-2026 sycophancy literature. The H2 second hypothesis, added in a recent cycle, has not yet had the consistency scrutiny the rest of the plan has received.
