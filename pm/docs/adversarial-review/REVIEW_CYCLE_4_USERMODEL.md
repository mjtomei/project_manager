# Review Cycle 4 — Literature Review: User-Modeling as a Lever on LLM Performance

Reviewer: fresh Claude session, blind to Cycles 1–3 during the independent pass below. The cross-reference appendix at the end was written after the independent review was drafted.

Source under review: `pm/docs/literature-review-user-model.md` (~9,556 words after Cycles 1–3).
Plan under review (context only): `pm/plans/plan-66d430f.md`.

This is Cycle 4. The methodology directs cycles to be progressively harder, and Cycle 3 reportedly predicted Cycle 4 should be short and convergence-reaching. I held that prediction at arm's length and went in looking for blood. What follows is what I actually found.

---

## Block 1 — Substance

### 1.1 Citations verified

I fetched/searched independent sources for the citations the cycle prompt flagged:

- **Choi/Transluce 2025** (https://transluce.org/user-modeling): the lit review's characterization checks out. Choi et al. (a) read from middle-layer residual-stream activations (layer 15 / layer 40 on 8B / 70B Llama-class models), (b) train LatentQA-style natural-language decoders that answer questions about user attributes (gender, age group, region, employment, marital status, occupation, religion, diet, exercise, country — the "~80 categories" claim is consistent with what the page shows), (c) demonstrate gradient-based and circuit-based steering that causally moves the subject model's behavior. The lit review's framing — "direct methodological *and* variable-side peer for Phase 1 / Phase 4" — is faithful and, if anything, slightly understates the overlap on the *transfer/closed-model* side (the LatentQA decoder *is* an output-token-style readout). The narrowing of the plan's novelty claim from "first user-modeling probe" to "first peer-ness-structured probe" is correct and necessary.

- **Fiske/Cuddy/Glick/Xu 2002** (JPSP 82(6):878–902): confirmed. The two-dimensional warmth/competence structure, the perceived-status → competence and perceived-competition → warmth predictions, and the warmth-as-perceiver-judgment framing are all faithfully described. *Warmth as the perceiver's judgment of the perceived* is unambiguous in the source ("people viewed as competitors are judged as lacking warmth, whereas people viewed as allies are judged as warm"). The lit review's added "Warmth-terminology note" is accurate. No competing interpretation in the literature treats warmth as a state of the perceiver — the lit review is safe here.

- **Cuddy/Fiske/Glick 2008** (Adv. Exp. Soc. Psych. 40:61–149): confirmed. The "universal dimensions" framing and the BIAS map extension match standard summaries.

- **Andreas 2022** (arXiv:2212.01681, EMNLP Findings): confirmed. The abstract supports the "structural reason to represent who is writing" framing. The lit review's caveat that Andreas is about the *author* and the plan extends to the *addressee* is accurate and well-flagged.

Independent verifications: at least four citations cross-checked against primary sources. No misrepresentations found.

### 1.2 The intellectual↔competence / moral↔warmth mapping

The lit review claims intellectual peer-ness maps onto SCM's competence dimension and moral peer-ness onto SCM's warmth dimension. This mapping is *defensible* but I want to be sharp about what's load-bearing and what's slippage:

- "Intellectual peer-ness ↔ competence" is clean. The sub-dimensions (technical competence, effort/seriousness, reasonableness) all fall within SCM's competence construct as Fiske defines it.

- "Moral peer-ness ↔ warmth" is *less* clean than the lit review acknowledges. SCM warmth is about *intent to harm or help* (cooperative vs. competitive intent), per Fiske's own evolutionary framing. The plan's moral peer-ness sub-dimensions (honesty/sincerity, good-faith engagement, mutual respect) overlap with SCM warmth but are not identical to it — *honesty* in particular is a competence-adjacent moral construct in many social-cognition literatures (e.g., the morality-as-third-dimension work; see Goodwin, Piazza, Rozin 2014 in JPSP, which explicitly argues morality is *separable* from warmth). The lit review currently treats the mapping as if SCM has one moral axis, when there's an open dispute about whether morality factors out of warmth.

  *Recommendation*: add a single sentence acknowledging the moral-vs-warmth-separability literature and citing Goodwin/Piazza/Rozin 2014 (Journal of Personality and Social Psychology 106(1):148–168, "Moral character predominates in person perception and evaluation"). The lit review doesn't have to take a side; it just has to say "we adopt the two-dimensional SCM partition; some social-psychology work argues morality is a separable third dimension — if so, the plan's moral peer-ness axis may decompose further in Phase 1's factor analysis." This actually *strengthens* the construct-validity falsification step the plan already has — it gives an alternative hypothesis the factor analysis can adjudicate.

This is the only Block-1 substance gap I found that has teeth.

### 1.3 Sycophancy reframe — applied consistently?

I traced "sycophancy" through every appearance:

- **Glossary (§Introduction)**: defines sycophancy as model behavior, explicitly notes "it sits on the opposite side of the causal arrow from peer-ness." Clean.
- **§5 first paragraph**: states the reframe directly. Clean.
- **§5 middle**: "sycophancy is mechanism-noise the plan is indifferent to" for non-truthfulness benchmarks. Clean.
- **§5 end ("Net effect on the design")**: "sycophancy is treated as a mechanism alternative to peer-ness in Phase 3, not as a confound to be eliminated at the input stage." Clean.
- **§7 predicted-outcomes table, row 5**: "Steering finds an LLM-behavior direction (e.g., sycophancy) rather than a user-modeling direction" — treated as a downstream mechanism alternative. Clean.
- **Templeton citation (§1)**: explicitly classifies "sycophantic praise" as an LLM-behavior feature, not a user-state feature. Clean.

The reframe is applied consistently. I cannot find a residual passage that treats sycophancy as an input-side confound. Score: pass.

### 1.4 Phase 1 standalone novelty after the Choi/Transluce narrowing

The lit review now claims Phase 1's contribution is the *structural* claim (two meta-axes, six sub-dimensions, factor structure pre-registered) rather than the basic feasibility of decoding user-side latents. This is the correct narrowing. But:

- Is "applying SCM's two-factor structure to LLM internals" actually a strong enough standalone contribution to justify a Phase-1-only publication? The lit review asserts yes. I think the answer is *yes, but barely*, and the lit review should be slightly more explicit about why. Specifically: the falsifiability of the factor structure (pre-registered loadings, factor analysis as falsification step) is what makes Phase 1 a contribution rather than a curiosity. The current text mentions pre-registration but doesn't drive home that *the falsification step is the contribution* — the alternative "we found these six probes" without a structural test would just be six new probes alongside Choi's eighty.

  *Recommendation*: in §7's "What the plan is and isn't claiming," tighten the Phase-1-novelty paragraph to lead with the falsifiability. One sentence: "Phase 1's contribution is not the probes themselves but the *test* of SCM's two-factor structure against LLM internals — a falsifiable structural claim adjacent to Choi/Transluce's flat 80-attribute decoding."

### 1.5 The natural failure mode the predicted-outcomes table doesn't promote

Cycle prompt 3.f asks whether the table covers "different model families show different results." The lit review handles this in *prose below the table* — the "few outcome shapes the table does not promote to top-level rows" paragraph. It's mentioned ("an effect present in some model families and absent in others"). But:

- The handling is too brief. "Common in steering papers — report as such" is not a real plan. What's the threshold for declaring the result model-family-specific vs. universal? How many model families is the plan running on? The lit review doesn't say, and the plan file should be consulted for this — but if the lit review is going to flag the failure mode, it should at least say "the plan runs on N model families; we treat the finding as universal only if it replicates across all N."

  *Recommendation*: either pull the model-family-specificity outcome up into the table as a sixth row, or expand the prose paragraph to specify a replication criterion. I'd vote for the table promotion because the table is the load-bearing pre-registration artifact.

### 1.6 The Resolution V at 16 cells specification — correct and well-explained?

The lit review states: "Resolution V is the design strength at which all main effects and all two-factor interactions can be estimated separately from each other (Resolution III, by contrast, aliases two-factor interactions with main effects — fatal here, because the whole point is to dissociate the axes). Sixteen cells is the minimum at which Resolution V is achievable for five two-level axes."

Fact-check: for a 2^5 design, the minimum-run Resolution V fractional-factorial is a 2^(5-1) = 16-run design. This is correct. The standard reference (Box, Hunter, Hunter; or NIST/SEMATECH e-Handbook) lists 2^(5-1)_V as the minimum Resolution V design for five factors at two levels. Pass.

Rationale-for-non-developer: the explanation is *adequate* but the term "aliasing" is dropped without gloss. "Aliases two-factor interactions with main effects" assumes the reader knows what aliasing means. Replacement: "Resolution III, by contrast, *confounds* (mixes together) two-factor interactions with main effects so you can't tell them apart — fatal here..." The word "confounds" is already in the reader's vocabulary; "aliases" is not.

### 1.7 Mediation-grade vs behavioral-grade standards — dual statement load-bearing?

The standards-mismatch resolution appears in two places:

- **§4 (line 107)**: "The plan's Phase 2 needs only behavioral-grade correlation evidence (probe + benchmark, correlated). The plan's Phase 3, where it claims causation of one direction on performance, needs interchange-intervention-grade evidence — *steering alone is sufficiency-only and does not clear the mediation bar*."
- **§7 (line 188)**: "§4's mediation-grade evidentiary bar applies to claims about *which internal representation* mediates a behavioral effect. The plan's Phase 2 (correlation between probed peer-ness and benchmark performance) clears a behavioral-grade bar; Phase 3 (the claim that the peer-ness vector causes the performance change) must clear the interchange-intervention bar..."

The dual statement *is* load-bearing — §4 needs it to disambiguate the evidence-grade column in the table, and §7 needs it to set up the mediation discussion. They're saying the same thing twice but for different local purposes. Keep both. The §7 version cross-references §4 ("§4's mediation-grade evidentiary bar applies"), which is the right approach. Pass.

### 1.8 §1 SCM treatment vs §7 SCM grounding callback — redundancy?

- **§1 (~line 46)**: introduces SCM, names the two papers, states the intellectual↔competence and moral↔warmth mapping, adds the warmth-terminology note.
- **§7 (~line 226)**: "Phase 1 alone — establishing the *structural* claim, that peer-ness sub-dimensions cluster into the predicted two meta-axes — is a publishable contribution. It adds peer-ness to the linear-representation map alongside language (Park 2024), sentiment polarity (Tigges 2023), truth (Marks 2023), refusal (Arditi 2024), and general user attributes (Choi 2025)."

These are *not* redundant. §1 introduces the construct; §7 ties it back to falsifiability and positions it in the interpretability landscape. The §7 callback is short and earns its space. Pass.

### 1.9 The §4 paper-summary table — earns its space?

The table at lines 111–124 (Paper / Variable probed / Evidence grade / Role for the plan) is genuinely useful. It does *not* duplicate the surrounding prose because the prose discusses papers one at a time without giving the reader a fast scan. The "Evidence grade" column in particular pays for the table on its own — that column is what makes "different papers clear different bars" actionable. Pass.

That said, two small issues:

- "Choi 2025 (Transluce)" row says "decoding + steered interventions" for Evidence grade. The Transluce page in fact demonstrates both gradient-based steering and circuit-based steering, and shows the decoder tracks circuit-based interventions it wasn't trained on. The table understates this. *Recommendation*: change "decoding + steered interventions" to "decoding + causal interventions (gradient + circuit-based)".
- "Hernandez 2024" row says "mixed (some non-linear)" — accurate but the "Role for the plan" column ("caveat: not all relations are linear") is too terse. Reader sees this and asks "so what?" *Recommendation*: change to "caveat: if a peer-ness sub-dimension turns out non-linear, fall back to SAE features."

### 1.10 Empirical contradictions

I didn't find any prior work contradicting the plan's core hypothesis that goes uncited. The Sclar 2024 prompt-sensitivity result is the closest thing to a load-bearing skeptic and is cited prominently. The Goodwin/Piazza/Rozin 2014 morality-separability work (see 1.2) is the only adjacent literature I'd add.

---

## Block 2 — Structure and readability

### 2.1 Length growth — has it produced padding?

The file is now ~9,556 words. Comparing to a typical lit review for an experimental ML paper (3,000–5,000 words is standard), this is on the long side. However, reading end-to-end, I don't find significant padding. The growth has gone into:

- Inline glosses (Block 3 work — necessary)
- The §4 paper table (earns its space — see 1.9)
- The predicted-outcomes table (earns its space — pre-registration)
- The §7 novelty-neighborhood enumeration (earns its space — this is the load-bearing novelty argument)
- The Choi/Transluce citation thread (necessary — narrows the novelty claim correctly)

The one section I'd consider for trimming is the Conclusion (§Conclusion: where the plan sits in the landscape). It restates the inheritance-and-divergence map that §7 already covers. The "Where the plan inherits cleanly" bulleted list and the "seed-lineage reading list" at the very end are partial duplicates of the per-section "Seminal anchors" footers. *Recommendation*: cut the "seed-lineage reading list" final paragraph entirely — it's a third recitation of citations already enumerated twice. Keep "Where the plan inherits / diverges / is genuinely novel" because those frame the contribution; cut the closing list.

Estimated word savings: ~250–300 words. Not huge, but it improves the ending.

### 2.2 Flow check (end-to-end as non-developer)

Reading the document straight through:

- Introduction: hooks well. The "treat it like a colleague" framing is concrete and earns the reader's attention. Pass.
- §1: theoretical anchors are clear. SCM treatment is well-paced. Pass.
- §2: framing-effects empirical results — concrete numbers, scale anchors present, flows well. Pass.
- §3: short and tight. Pass.
- §4: longest section, dense, but the "Why this section" opener and the table help a lot. Marginal pass — see Block 3 below for residual jargon.
- §5: clean reframe section. Pass.
- §6: short, tight, the open-vs-closed-model motivation is clear. Pass.
- §7: dense but earns it. The predicted-outcomes table is the highlight of the document. Pass.
- §8: standard benchmark walk-through, properly contextualized. Pass.
- Conclusion: too long (see 2.1).

The flow is generally good. No section disrupts the narrative. Pass overall.

### 2.3 Abruptness / transitions

Found one transition that's slightly abrupt: §4 → §5. §4 ends on "Methodological adjacency: LatentQA (Pan et al. 2024). Caveat: Hernandez 2024 on non-linear cases" and §5 opens with "Why this section. The obvious alternative explanation..." A one-line bridge would help: "With the interpretability toolkit in hand, the next question is what *other* mechanism could explain a framing-to-accuracy effect. The most obvious alternative is sycophancy."

### 2.4 Hooks / punchy lines

The document has good ones already ("the model has lungs"; "framing changes performance, and not always for the better"; the Sclar "A to F from whitespace" framing). No additional hooks needed.

---

## Block 3 — Non-expert accessibility (load-bearing)

After three cycles of accessibility passes, most jargon has been glossed. What survives:

### 3.1 Undefined / under-glossed terms still load-bearing

- **"aliases"** (§7 fractional-factorial paragraph): used as a technical statistics term ("Resolution III aliases two-factor interactions with main effects"). Target reader will not know this. *Replacement*: "confounds (mixes together)." See 1.6.

- **"fractional factorial"** (§7): introduced with a parenthetical gloss but the gloss is itself a bit dense. The current text says "a way to test multiple variables at once without trying every combination. With five on/off switches (politeness, respect, honesty, good-faith, effort), there are 32 combinations; running all 32 with enough samples each is expensive. A fractional factorial picks a careful subset chosen so that each switch's main effect can still be estimated separately." This is actually fine — the gloss is concrete. Pass on second look.

- **"factor-analyze"** / **"factor structure"** (§7 construct-validity step): used without gloss. Target reader does not know what factor analysis is. *Replacement*: "After Phase 1 extracts the six probe directions, we apply factor analysis — a standard statistical method that asks 'do these six measurements really cluster into two underlying dimensions, or some other number?' — and check whether the empirical clustering matches SCM's predicted two-meta-axis structure."

- **"pre-register"** / **"pre-registration"** (§7): glossed inline once ("Listing the possible outcomes before running the experiment is called *pre-registration*") — good. But the word is then reused multiple times. The first-use gloss is in the right place. Pass.

- **"counterfactual statement"** (§4, Park 2024 paragraph): "Park et al. give the formal counterfactual statement: probe directions ... and steering directions ... are mathematically connected via a non-Euclidean inner product respecting language structure." "Non-Euclidean inner product" is jargon the target reader has zero chance of parsing. *Replacement*: rewrite the sentence as "Park et al. give the formal mathematical link: probe directions (used to read out a concept) and steering directions (used to push a concept up or down) are connected by a precise geometric relationship that respects how the language model's internal space is shaped. Practically, this means a direction extracted by probing can be used for steering, and vice versa."

- **"ablate"** / **"ablation"** (§4 Arditi paragraph, §7): used at lines 142 ("find the direction, ablate or amplify") and line 188 ("activation-patching or ablation of the candidate direction"). Glossed nowhere. Target reader does not know this term. *Replacement*: first use, "ablate (zero out, like turning a knob to zero)." Then reuse.

- **"LoRA"**: does not appear in the lit review (only on the Transluce page I fetched). Not a problem.

- **"linear classifier"** (§4, line 107): used without gloss in "*probe* — a small companion model trained to look at the scratchpad and answer one yes/no question." Wait — re-reading, the gloss for "probe" *is* in the §4 glossary. But "linear classifier" appears in §4 line 107 ("read by linear classifiers") *outside* that gloss list. Target reader still doesn't know what makes a classifier "linear." *Replacement*: "(linear classifiers — the simplest kind of probe, which just multiplies the scratchpad values by a fixed set of weights and adds them up)."

- **"residual stream"** glossed once in §4 but then used unqualified in §1 (line 22: "decodable from the residual stream") *before* §4 introduces the term. *Recommendation*: §1 first use should gloss inline: "decodable from the residual stream (the network's running internal scratchpad — glossed in §4)."

- **"causal mediation"** (§Introduction phase 3 description; §4 glossary; §7 throughout): glossed in §4. But it appears in the §4 paper table ("causal mediation" as an evidence grade) *before* the inline gloss. The §4 glossary appears at lines 94–105; the table is at lines 111–124. So order is right. Pass.

- **"fine-tuning"** / **"fine-tuned"** (§5, §6): used without gloss. Target reader may know roughly what fine-tuning means but the lit review uses it load-bearingly ("RLHF-trained ones"; "fine-tuned models predict their own behaviors"). *Replacement, first use in §1 glossary or §5*: "fine-tuning — a small additional round of training on a specific dataset, applied after the main pretraining is done, to specialize the model's behavior."

- **"checkpoint"** (§7 predicted-outcomes prose paragraph: "appears only in RLHF-tuned checkpoints versus base models"): undefined. *Replacement*: "(a checkpoint is a saved version of the model at a particular point during training)."

- **"GSM8K"**, **"MMLU"**, **"HumanEval"**, **"TruthfulQA"**, **"FEVER"** — all introduced with one-line glosses in §8. Pass.

- **"BIG-Bench Hard"** (§6, Turpin paragraph): the lit review already glosses this inline ("a benchmark suite of 23 difficult reasoning tasks..."). Pass.

- **"inverse scaling"** (§5): glossed inline. Pass.

- **"contamination"** (§8 last paragraph: "HumanEval and MMLU have appeared in enough training corpora that contamination is a known issue"): used without gloss. Target reader doesn't know what corpus contamination means. *Replacement*: "(contamination — the benchmark questions accidentally appearing in the training data, which inflates apparent scores)."

### 3.2 Section openings — "why should I care" check

- §1 opening: "Two threads of prior work converge on the plan's hypothesis." — fine, frames the reader's takeaway.
- §2 opening: "This is where the plan's anecdote ... meets published numbers." — concrete, earns attention. Pass.
- §3 opening: "§3 looks at the alternative the plan must beat in production..." — clear. Pass.
- §4 opening: "Why this section. The plan needs to (a) read out a number for 'how peer-like does the model judge the user to be' and (b) change that number on purpose to see if performance changes." — excellent. Pass.
- §5 opening: "Why this section. The obvious alternative explanation..." — clear. Pass.
- §6 opening: "Why this section. The plan's interpretability machinery only works on open models..." — clear. Pass.
- §7 opening: "Why this section. This is the section that decides whether the plan is publishable." — punchy. Pass.
- §8 opening: "§8 walks through the standard accuracy benchmarks the plan will use." — adequate but the weakest opener; "the selection criterion: hard correctness signals..." rescues it. Marginal pass.
- Conclusion opening: "The plan stitches together established research threads in service of one underexplored measurement..." — fine.

### 3.3 Numbers without scale anchors

- "10 percentage points on average — comparable in size to switching to a more capable model class. (For scale, switching from GPT-3.5 to GPT-4 on the same tasks is a 15–20 point jump...)" — anchored. Pass.
- "up to 76 percentage points on LLaMA-2-13B. (For scale: 76 points means a model that scores 80% on one phrasing scores 4% on a trivially-rephrased version — the difference between an A and an F from changing whitespace.)" — anchored. Pass.
- "TruthfulQA jumps from 32.5% to 65.1% on Alpaca — roughly doubling correctness." — anchored. Pass.
- "thirteen open chat models up to 72B parameters" — *not* anchored. Target reader does not know whether 72B is large or small. *Replacement*: "up to 72B parameters (comparable to the largest open models then available; GPT-4 is estimated to be substantially larger)."
- "tens of millions of SAE features" (§1, Templeton paragraph) — not anchored. Is that a lot? *Replacement*: "tens of millions of SAE features — a feature catalog roughly the size of a large encyclopedia, each entry corresponding to one interpretable concept the model represents."

### 3.4 Names dropped without context

- **"Karpathy"** (§2 last paragraph): glossed inline this cycle. Pass.
- **"Anthropic"** (§3, §6): used without context. Most target readers will recognize Anthropic as "the Claude company" but a one-line gloss on first use ("Anthropic, the company that makes the Claude model family") wouldn't hurt.
- **"Alpaca"** (§4, line 140): "Truthfulness on TruthfulQA jumps from 32.5% to 65.1% on Alpaca" — Alpaca is dropped without gloss. Target reader does not know what Alpaca is. *Replacement*: "...on Alpaca (a Llama-derived open chat model)..."
- **"GSM8K"** is introduced in §3 (line 86: "beat hand-designed prompts on GSM8K by up to 8 percentage points") *before* §8 glosses it. *Recommendation*: §3 first use should gloss inline: "GSM8K (a standard grade-school math word-problem benchmark; see §8)."
- **"Llama"**, **"Llama 2"**, **"Gemma"** — referenced without context. *Recommendation*: first use in §Introduction glossary line on open models could expand to "Llama (Meta), Gemma (Google)."

### 3.5 Implicit prior-art assumptions

- §4 assumes the reader has some intuition for "linear" representations as a *concept* distinct from "non-linear." The glossary entry on linear representation helps but reader who hasn't thought about high-dimensional vector spaces will struggle. A concrete one-sentence example would help: "Example: if 'positive sentiment' is linearly represented, you can find a single direction in the scratchpad such that moving the activation a little along that direction makes the model's output more positive, and a little the other way makes it more negative."

### 3.6 Insider quips

I did not find any "you know how it goes" / "modulo the usual" / in-group hedging. Past cycles seem to have cleaned these out. Pass.

### 3.7 Abstract claims without concrete examples

- The §1 SCM paragraph could use one concrete example. The mapping "intellectual peer-ness ↔ competence" is abstract; a reader who's never thought about SCM will not immediately know what counts as a "perceived as competent" framing. *Replacement, add one sentence*: "Concrete example: when a user opens with 'I've been working on X for two weeks and I'm stuck on this specific edge case,' SCM would predict the model perceives high competence; when a user opens with 'do my homework,' SCM would predict low competence."

- The §Introduction "training-data-imitation" paragraph is currently abstract. The example given ("a senior engineer reviewing a colleague's design proposal writes differently than the same engineer dismissing a low-effort question from a stranger") *is* concrete. Pass.

---

## Convergence assessment

**The findings have largely reached the convergence threshold, but not entirely.** Of my Block 1 findings, one (1.2 — the moral-vs-warmth-separability literature, Goodwin/Piazza/Rozin 2014) is genuinely substantive and was not addressed in the lit review's three prior cycles (I'll verify in the appendix below). Two more (1.5 model-family-specificity outcome row; 1.4 Phase 1 falsifiability lead) are minor structural improvements rather than nitpicks.

Block 2 produced one real cut (the closing seed-lineage reading list) and one small flow improvement.

Block 3 produced a handful of legitimate remaining-jargon catches ("aliases", "factor-analyze", "ablate", "non-Euclidean inner product", "contamination", scale-anchor on 72B parameters) that the prior cycles' accessibility passes missed. These are *real* findings, not phrasing nitpicks — a non-developer reader would actually trip on them.

**Cycle 3's prediction that Cycle 4 should be short and convergence-reaching: half-right.** This review is shorter than Cycle 3's would have been if Cycle 3 caught everything, but I produced ~5 substantive findings (Goodwin/Piazza/Rozin; model-family row; Phase 1 falsifiability lead; the §4 table evidence-grade understatement on Choi; the §4→§5 transition) plus ~10 accessibility catches that have real teeth. That's more than "nitpicks of phrasing." Convergence threshold *not* fully reached.

**Prediction for Cycle 5**: a Cycle 5 *is* warranted, but it should be short — focused on (a) the Goodwin 2014 / moral-third-dimension question, which is a real construct-validity issue and the response cycle should fetch that paper and decide whether to cite it; and (b) the remaining accessibility catches above. After Cycle 5 incorporates those, the document should genuinely be at the "nitpicks of phrasing only" floor and Cycle 6 would be excessive. So: Cycle 5 yes, Cycle 6 no. This is one cycle short of the sibling regression-loop lit review's three-cycle pattern, which is consistent with this artifact starting from a more developed baseline.

---

## What prior cycles missed (cross-reference, written after independent review)

I now scanned the three prior review cycles and their response files. Findings:

### What I caught that prior cycles did not

- **Goodwin/Piazza/Rozin 2014 moral-vs-warmth separability** (1.2 above): None of Cycles 1, 2, or 3 raised this. The lit review's "moral peer-ness ↔ warmth" mapping has been treated as uncontroversial across all three cycles, but the social-psychology literature has a real dispute about whether morality factors out as a third dimension separable from warmth. This is the strongest substantive finding in my review and is genuinely new.

- **"Non-Euclidean inner product" jargon in §4 Park 2024 paragraph** (3.1): I don't see this flagged in any of the three prior cycles' accessibility passes. Either the phrase was added during Cycle 3's edits and not re-passed for accessibility, or all three reviewers gave the Park paragraph a free pass on jargon.

- **"Aliases" in the fractional-factorial paragraph** (3.1 / 1.6): not flagged in prior cycles. Same likely cause — added during a recent expansion, not re-passed.

- **"Ablate" used without gloss** (3.1): not flagged.

- **The §4 paper-table understatement of Choi/Transluce's evidence grade** (1.9): not flagged. The table was added in Cycle 3 and the Choi entry undersells what the Transluce page actually demonstrates.

- **The 72B parameters scale anchor** (3.3): not flagged in prior cycles.

- **The closing "seed-lineage reading list" being a third recitation** (2.1): not specifically flagged, though Cycle 2 raised general concerns about the conclusion's length.

### Where prior cycles caught things I would have

- The Choi/Transluce citation was correctly added in (I believe) Cycle 2 or Cycle 3 based on a prior reviewer's catch. Independent verification confirms the citation is real and the lit review's characterization is faithful. Prior reviewer got this right.
- The sycophancy reframe (Cycle 2 or 3) is applied consistently. Prior reviewer got this right.
- The Resolution V at 16 cells specification (Cycle 3) is correct. Prior reviewer got this right.
- The mediation-grade vs behavioral-grade distinction (Cycle 2 or 3) is well-handled. Prior reviewer got this right.

### Where prior cycles raised things I downgrade

- The §1 SCM vs §7 SCM callback was flagged as potential redundancy. I disagree on independent reading — they say substantively different things and the §7 callback earns its space. Keep both.
- The §4 paper-summary table was flagged as possibly duplicating prose. I disagree — the Evidence-grade column alone pays for the table.

### Net assessment

Cycles 1–3 did genuine work, particularly on the Choi/Transluce citation (a major substantive fix) and the sycophancy reframe (a major conceptual fix). Cycle 4 catches one real substantive miss (Goodwin 2014) and a residual layer of accessibility catches in the most recently edited paragraphs. After Cycle 5 addresses those, the artifact is done.
