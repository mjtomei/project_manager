# Review Cycle 8 — Literature Review: User-Modeling as a Lever on LLM Performance

Reviewer: blind Cycle-8 pass. Date: 2026-05-15. Word count of artifact: ~13,800.

The artifact has clearly been through many cycles. The substance is, on the whole, defensible. Most of what's left is accessibility, prose, and a small handful of structural moves. I will not manufacture substantive findings. Where prior art is at issue, I'll narrow rather than collapse.

---

## Block 1 — Substance

### B1-1. The "training-data-imitation" mechanism is still the weakest theoretical link, and the artifact knows it but doesn't say so cleanly.

§1 line 53 contains the load-bearing concession:

> "The 'humans calibrate effort by perceived peer-ness' claim is itself a hypothesis. The plan's result tests it indirectly: if LLMs trained on human text show the effect, the human pattern is more likely real."

This is fine as a hedge but it tucks a major epistemic point into a tail sentence. The whole mechanism story chains *three* claims: (a) humans calibrate effort by perceived peer-ness, (b) the calibration leaks into next-token statistics, (c) LLMs reproduce it. A positive Phase 2 result is consistent with at least three alternative mechanisms the artifact does not name:

- The model has learned a generic "high-effort prompt → high-effort response" register-matching rule that has nothing to do with peer-ness perception specifically (Sclar 2024 noise floor speaks to this — formatting alone moves 76 points).
- The model has learned a "high-status interlocutor → cautious output" rule from corporate / formal genres without peer-ness being the underlying variable.
- RLHF reward signal post-training has installed a "be more careful when the user seems sophisticated" policy that bypasses the pretraining-imitation story entirely.

**Severity**: substantive but not novelty-killing. **Fix**: in §1, after the training-data-imitation paragraph, add one paragraph naming the three alternatives explicitly and noting Phase 3's per-direction steering (against independently-extracted register / RLHF-policy directions) as the disambiguator. Currently §7's table mentions only the sycophancy alternative.

### B1-2. The Phase 4 calibration story is under-specified and the artifact admits this but in a way that propagates risk to readers.

§6 says Phase 4 calibrates closed-model self-report against the open-model Phase 1 *correlational* probe. §6 also notes: "Phase 4's transfer therefore inherits Phase 1's evidence bar, not Phase 3's." That is correct but the consequence isn't drawn: **a positive Phase 4 result on a closed model is behavioral-grade only — it cannot claim the verbalized readout maps to a causally-validated direction.** This matters because Phase 4 is the half of the plan that production users care about. Anyone reading "Phase 4 transfers to closed models" is going to assume the closed-model number means what the open-model number means. The artifact should state, in §6 and again in the conclusion, that the closed-model readout is *correlationally* calibrated and a positive result there does not establish that closed models have a causally-mediating peer-ness representation — only that the verbalized self-report tracks the open-model probe well enough to be useful.

**Severity**: substantive. Affects how the plan's headline result will be read.

### B1-3. The Goodwin third-factor alternative is named but never operationalized in Phase 1's exploratory factor analysis.

§1 and §7 both flag Goodwin/Piazza/Rozin 2014 as the morality-as-separable-third-dimension alternative to SCM. §7's predicted-outcome table includes a Goodwin-shaped row. But the methodology never says *what test* in the factor-analysis output would distinguish "two-factor (intellectual + moral) SCM" from "three-factor (sociability + morality + competence) Goodwin." Eigenvalue threshold? Parallel analysis? BIC on factor count? The artifact handwaves "factor analysis" without committing.

**Severity**: substantive but methodologically narrow. **Fix**: one-sentence pre-commitment to a factor-retention rule (parallel analysis is the modern default; Kaiser's K1 rule is the old default and frequently overstates factor count).

### B1-4. Wang et al. 2026 is named as a "partial pre-replication target" but the claim doesn't quite hold.

§5 line 215 says of Wang:

> "Wang reports a *null* on internal encoding of user authority specifically — and Wang's claim is itself a probe finding, not just an input-framing finding, which makes it the closest published piece of evidence against Phase 1."

Then: "Phase 1 will test whether the SCM-anchored intellectual-competence dimension (broader and more concrete than 'authority') yields a positive result."

The logic chain is: Wang finds nothing on "authority"; the plan tests "intellectual competence"; therefore Phase 1 could go either way. But "competence" and "authority" are not subtle distinctions in social-psychology terms — they're *the same SCM cell*. SCM's competence dimension is operationalized in Fiske/Cuddy/Glick/Xu 2002 via items including "competent," "confident," "capable," "skillful," **"powerful," and "high status."** Wang's "authority" probably loaded on the SCM competence dimension if measured directly. The artifact needs either (a) to commit to a definition of intellectual competence that demonstrably *excludes* authority, or (b) to acknowledge that a Phase 1 null on intellectual competence is the expected outcome given Wang.

**Severity**: substantive. The current framing of Wang as "partial pre-replication target" overstates how cleanly the plan's competence dimension is different from Wang's authority probe.

### B1-5. Sample size, statistical power, and multiple comparisons go unmentioned.

For a literature review that is upstream of a multi-phase empirical plan with five framing axes × Resolution V × six benchmarks × N model families × N sub-dimensions, the question "what effect size is the plan powered to detect, and at what alpha after multiplicity correction" is never raised. The closest the artifact gets is the Sclar prompt-formatting noise floor mention in §3.

This isn't a literature-review-level problem strictly speaking — the *plan* should answer this — but the lit review should at least *flag* the multiple-comparisons risk given the fractional-factorial design, because the plan's predicted-outcome table has six rows each of which is implicitly a separate hypothesis.

**Severity**: substantive but procedurally borderline (lit review vs. plan). **Fix**: one sentence in §7's fractional-factorial subsection: "With six sub-dimension probes evaluated against five framing axes and N benchmarks, family-wise error control (e.g., Holm-Bonferroni on per-sub-dimension main effects, BH-FDR on interactions) is a precondition for the table's rows being interpretable as independent findings."

### B1-6. "Standard gradable benchmarks" gets repeated as a virtue but the artifact never confronts that MMLU/HumanEval contamination potentially nullifies the whole Phase 2 effect.

§8 line 334 says:

> "HumanEval and MMLU have appeared in enough training corpora that contamination... is a known issue. The plan should treat *relative* movement under matched-content paraphrases as the load-bearing signal, not absolute accuracy."

This is the right move but it is buried at the end of §8. If contamination has saturated MMLU then the framing-effect signal has very little headroom on MMLU items the model already gets right. The artifact should escalate this: name a non-contaminated benchmark (LiveBench, SWE-Bench Verified, recent fresh-question evaluations from HumanEval-X or BBH-extra) as the *primary* DV, with MMLU/GSM8K as anchors-to-prior-literature secondary.

**Severity**: substantive. Affects whether Phase 2 has signal at all.

---

## Block 2 — Structure and readability

### B2-1. §4 is too long and front-loads vocabulary before motivation.

§4 spans roughly 90 lines and opens with a 10-bullet vocabulary glossary, then a table of 16 papers, then prose discussion. A reader arriving at §4 without a prior interpretability background will close the tab during the glossary. The section's "why this section" hook ("the plan needs to read out a number and change that number") is good — but it is immediately followed by the densest jargon block in the document.

**Fix**: defer the full glossary to the end of §4 as a reference glossary; in the body, gloss each term inline on first use. Or split §4 into §4a (probing — Subramani / Turner / Zou / Park) and §4b (causal — Tigges / Marks / Arditi / Li / interchange).

### B2-2. The §1 glossary and the §4 glossary repeat conceptually but not literally.

§1 has a six-item glossary (LLM, open vs closed, RLHF, sycophancy, persona prompt, role-play, conference acronyms). §4 has a ten-item glossary (residual stream, activations, probe, contrast pairs, steering vector, SAE, activation patching, causal mediation, refusal direction, linear representation). Neither references the other. A returning reader doesn't know where to find the gloss for "probe" without scanning. **Fix**: at top of document, a single Glossary section or a "see §4 for interpretability vocabulary" pointer in §1.

### B2-3. §7 (novelty and prior art) is the most important section for the target reader, but is structurally buried at position 7 of 8.

A PM or adjacent researcher evaluating whether to use `pm` and whether the plan's hypothesis is supported by science will reach the novelty story last, after wading through three sections of interpretability tooling. The artifact's own claim — what's genuinely new about the plan — sits in §7's "What the plan is and isn't claiming" subsection. **Fix**: either move that subsection up to §1's introduction (after the four-phase summary) as a "what's new" callout, or add a forward pointer in §1 saying "for the contribution claim relative to the closest published peers, jump to §7's neighborhood enumeration."

### B2-4. The conclusion repeats the §1 hypothesis nearly verbatim but doesn't reinforce the *narrowed* contribution claim.

The conclusion (line 338+) says "the plan combines established interpretability methods with a measurement problem the prior literature hasn't isolated" — the *old* (broader) framing. The actual narrowed four-part contribution is enumerated only in §7 ("variable, DV, design, closed-model transfer") and the conclusion punts ("not re-stated here"). Punting is the wrong move at the conclusion of a 14,000-word document — the reader needs the punch line repeated, not deferred. **Fix**: copy the four-part residual contribution list verbatim into the conclusion.

### B2-5. Section flow §5 → §6 is abrupt.

§5 closes on Ibrahim et al.'s warmth-fine-tuning result and the sycophancy-vs-peer-ness profile. §6 opens cold on "If you only use ChatGPT or Claude through their app or API..." There is no bridge from "sycophancy is on the behavior side of the causal arrow" (§5) to "introspection lets us read internal state via output tokens" (§6). The connecting thread is: *if closed models hide everything, including the sycophancy directions, then Phase 4's job is to read the user-modeling state out of the visible output tokens.* **Fix**: a one-sentence bridge.

---

## Block 3 — Non-expert accessibility (LOAD-BEARING)

### B3-1. Undefined jargon (still — even after multiple cycles)

The following terms appear load-bearingly without an inline gloss, and a non-developer reader will not know them:

- **"residual stream"** (§1 line 22) is glossed only in §4, but appears in §1, §4, §5, §6, §7. Forward reference to §4 is not enough; gloss it inline at §1 first use. **Proposed gloss**: "the network's running internal scratchpad (technical term: 'residual stream' — see §4)".
- **"linear probe"** (§1 line 47, §4, §7) — used loadbearingly in §1 before any gloss. **Proposed gloss**: "a small detector that learns to read one yes/no signal out of the scratchpad."
- **"interchange intervention"** (§4 line 118, §7) — glossed in §4 but the gloss assumes the reader already understands a "model run" and "the right point." **Proposed simpler gloss**: "the strongest causal test: run the model twice on two different inputs, copy a piece of its internal state from one run into the other, and check whether the second run's answer flips the way the first run's state predicted."
- **"contrast pairs"** (§1 line 22, §4) — used in §1 without gloss; glossed in §4. **Proposed §1 gloss**: "carefully matched prompt pairs differing in exactly one thing."
- **"fractional-factorial design"** / **"Resolution V"** (§7) — has a paragraph-long gloss, but the gloss itself uses "main effect," "aliasing," and "two-factor interactions" without glossing those. **Proposed simpler restatement**: "Five things you might vary (politeness, respect, honesty, good-faith, effort) make 32 possible combinations. Running all 32 wastes effort. A fractional-factorial design picks 16 specific combinations that, by careful selection, still let you measure each variable's effect on its own, and whether any two interact. We use 16 because that's the smallest set that achieves this — the technical name for that strength is 'Resolution V.'"
- **"causal mediation analysis"** — glossed in §4 line 113 as "a statistical tool for testing which intermediate variable carries an effect from cause to outcome." That gloss is fine but appears before the reader knows what "intermediate variable" means in this context. **Fix**: lead with the salt example (which is already in §4 line 128) and use it to ground the term *before* defining it formally.
- **"factor analysis"** (§1, §7) — used loadbearingly. §7 line 277 has a parenthetical gloss but it's late. **Proposed §1-first-use gloss**: "factor analysis — a statistical test for whether several measured signals actually trace back to a smaller number of underlying axes."
- **"calibration"** (§6, §1) — used in two senses. In §1 it means "humans adjust effort based on perceived peer-ness"; in §6 it means "convert closed-model self-report scale to open-model probe scale." The two meanings collide and the reader doesn't know which one is which on a second encounter. **Fix**: rename the §1 usage to "tune their effort" or "adjust their effort" to free "calibration" for the technical §6 usage.
- **"benchmark"** (passim) — load-bearing but never defined. **Proposed first-use gloss (§1)**: "benchmark — a standardized test problem set (like SAT for AIs) where the answers are known so accuracy can be measured."
- **"pretraining" vs "post-training" vs "RLHF" vs "fine-tuning"** — these four terms are used somewhat interchangeably across §1, §4, §5. RLHF is glossed in §1; pretraining and post-training and fine-tuning are not. A non-developer doesn't know that pretraining is the giant-text-corpus step, post-training is the instruction-tuning + RLHF step, and fine-tuning is a small targeted update on top. **Fix**: one paragraph in §1's glossary distinguishing the three stages.
- **"MMLU," "GSM8K," "HumanEval," "TruthfulQA," "FEVER," "BBH"** — appear in §5, §6, §8 before §8 explains what they are. The target reader doesn't know these are benchmarks vs. methods vs. companies. **Fix**: §1's glossary should include "the major LLM benchmark names you'll see in this review — MMLU, GSM8K, HumanEval, TruthfulQA, FEVER — are all detailed in §8."

### B3-2. Implicit prior-art dependencies the target reader doesn't have

- §1 line 47 mentions "linear probe setting" and assumes the reader knows the linear-probe / non-linear-probe distinction matters. **Fix**: gloss linear-probe inline before invoking the distinction.
- §4 paragraph 4 references "RepE, ActAdd, CAA" as three names for the same recipe — useful for a researcher but noise for a non-expert. **Fix**: a single sentence: "Three papers gave this recipe three names — we use whichever name each cited paper uses, but they're interchangeable in practice."
- §7 line 254 references "Phase 2 clears a behavioral-grade bar; Phase 3 the interchange-intervention bar" without re-stating what those bars are, three pages after §4. **Fix**: inline reminder.

### B3-3. Unmotivated framings

- §1 line 5 opens: "The plan ... formalizes a guess working programmers make privately." This is a casual hook but it assumes the reader is a working programmer or knows what one's private guesses sound like. A PM or adjacent researcher may not have this experience. **Proposed rewrite**: "The plan formalizes a working hypothesis many practitioners have noticed informally: LLMs produce better work when the user's prompt treats them as a thoughtful collaborator rather than as a tool to bark commands at."
- §1 line 18: "*LLMs need no genuine perception of equality, only enough human collaboration text to internalize the pattern.* No claim about machine social cognition is required." The reader hasn't yet been told why "machine social cognition" would be an objection. **Fix**: add half a sentence: "(This sidesteps a contentious debate over whether LLMs 'understand' anything — the plan's prediction doesn't depend on the answer.)"
- §4 line 120: "Different papers below clear different bars; the table flags which." Good signposting, but the table-and-bars structure is itself unfamiliar territory and the reader doesn't yet know why three bars exist. The evidence-grade table at line 122 should come *before* the methodological-papers table, not after — currently the order is "vocabulary → evidence grades → papers" but the prose lands evidence grades *between* them.

### B3-4. Abstract claims without concrete examples

- §1 line 18, "humans calibrate effort, care, and rigor based on whether they perceive their collaborator as an equal — they invest more, hedge less carelessly, check their work more readily when working with someone they respect." This is the load-bearing mechanism claim and it's abstract. **Proposed concrete example**: "A code reviewer responding to a junior engineer who clearly read the docs writes a different review than the same reviewer responding to a one-line drive-by question. The first response will engage with the technical content; the second may just point to the docs. LLMs trained on millions of such exchanges have internalized that pattern."
- §3 line 91, the AGENTS.md/CLAUDE.md description is abstract — what does one of these files actually contain? **Proposed concrete addition**: "A typical CLAUDE.md says things like: 'this project uses pytest, run tests with `pytest -xvs`; the database tests need PostgreSQL running locally; never edit `migrations/` by hand.' It's the operational handbook the AI is told to read first."
- §7 line 266, the politeness/respect/honesty/good-faith/effort axes are listed but no example prompts are given for each. **Proposed concrete additions** (one example per axis):
  - polite-but-effortless: "Please fix my code for me, I can't be bothered to look at it."
  - impolite-but-high-effort: "This is broken, I tried debugging for an hour, here's a minimal repro and three hypotheses about what's wrong."
  - dishonest-but-respectful: "I know what I'm doing here; just write the function" (when in fact the user doesn't).

### B3-5. Dense paragraphs (>5 sentences or multi-idea)

- §1's paragraph at line 18 is 5 sentences carrying three ideas (mechanism, training corpus, prediction). Split after sentence 2.
- §4's paragraph at line 187 (Anthropic NLA paragraph) is 7 sentences and packs Patchscopes + Activation Oracles + NLA + Phase 4 inspiration + Phase 1 fallback into one breath. Split into three paragraphs: (a) Patchscopes precedent, (b) Anthropic NLA stack, (c) Phase 1/4 implications.
- §5's Wang-et-al paragraph at line 215 is 10 sentences and is the densest paragraph in the document. Split into three: (a) what Wang did and found, (b) why the result is consistent with the peer-ness framing, (c) the partial-pre-replication-target framing for Phase 1.
- §7's paragraph at line 293 (residual contribution enumeration) is 6 sentences and lists four things; the four things would be clearer as a bulleted list.

### B3-6. Names dropped without context

- "Andrej Karpathy" (§2 line 81) — glossed once as "a widely-followed practitioner who publishes general-audience tutorials." Adequate.
- "Murray Shanahan" (§2 line 79) — described as conceptual companion but no gloss of who Shanahan is. **Fix**: "(Shanahan is a senior AI researcher whose work shaped the role-play-as-simulation framing — see Nature 2023.)"
- "Atticus Geiger" (§7 line 257) — names appear without context. Researchers will recognize; PMs won't. **Fix**: gloss as "Geiger and collaborators developed the interchange-intervention framework now standard in interpretability."
- "Ethan Perez" (§5 line 197) — no gloss; cited as if the reader knows him. **Fix**: "(Perez is at Anthropic on the alignment team and led the model-written-evaluations work that first quantified sycophancy at scale.)"
- "transluce.org" (§4) — glossed once as a publication venue ("Transluce") but not as a research organization. **Fix**: "Transluce is a non-profit AI interpretability research lab; the user-modeling work is one of their flagship results."
- "transformer-circuits.pub" (§4, §6) — glossed in §6 as "Anthropic's in-house publication venue for interpretability research — not peer-reviewed but high-quality." Good. Move that gloss to §4 first use.
- "AAAI / NeurIPS / ICLR / ICML / ACL / EMNLP / NAACL" — §1 glosses these as a group. Good. But "NeurIPS Spotlight" (§1) glossing as "top ~5%" is correct but doesn't say why the reader should care. **Fix**: "(A NeurIPS Spotlight is roughly equivalent to a paper that journal reviewers in another field would call a 'highly recommended' or 'editor's pick' result.)"
- "OLMo," "Llama," "Gemma" — used without glosses. Llama is famous enough to skate; OLMo and Gemma less so. **Fix**: parenthetical "OLMo (the open-weights model from Allen AI), Gemma (Google's open-weights line)."

### B3-7. Insider-only quips / hedging

- §1 line 35 mid-Stachan parenthetical: "Shanahan et al. argue this is a more accurate description of what happens than 'the model has an identity.'" The reader hasn't been told what "having an identity" would mean as the alternative. **Fix**: spell out what's at stake.
- §3 line 93: "(For scale: 76 points means a model that scores 80% on one phrasing scores 4% on a trivially-rephrased version — the difference between an A and an F from changing whitespace.)" — *excellent*. This is the model for how scale anchors should be done throughout. Apply elsewhere.
- §7 line 305 table cell: "useful finding even if not the strongest version." This is an in-group "we'd still publish it" hedge. **Fix**: drop or replace with "still informative because it isolates the training-data dependence."

### B3-8. Quantitative claims without scale anchors

Mostly handled well after prior cycles. Remaining offenders:

- §2 line 73: "the effect is up to 30 percentage points on GPT-4.1-nano and around 8 points on GPT-4o, monotone in model scale." "Monotone in model scale" is unglossed for a non-expert. **Fix**: "...and the effect grows steadily with model size — the smaller the model, the bigger the framing effect on it."
- §4 line 169: "Truthfulness on TruthfulQA jumps from 32.5% to 65.1% — roughly doubling correctness." The anchor "roughly doubling" is good. But the reader doesn't know whether 65% is high or low *in absolute terms* on TruthfulQA. **Fix**: "...roughly doubling correctness on a benchmark where even strong contemporary models scored under 50%."
- §5 line 201: "warm-tuned variants show 10–30 percentage point higher error rates." Error rate of what — fraction wrong, fraction harmful, fraction confused? The Ibrahim abstract specifies. **Fix**: "10–30 percentage point higher rates of *false answers* on safety-critical questions."

### B3-9. Acronym creep

- **PSM** introduced in §1 line 55 and used again in §7. The first use spells it out. Good.
- **DV / IV** used heavily throughout. §1 spells them out once but the abbreviations are then re-used without reminder for 13,000 words. **Fix**: §1 glossary entry: "DV = dependent variable = the thing you measure; IV = independent variable = the thing you change."
- **SCM** introduced in §1 line 47 ("Stereotype Content Model (SCM)"). Good.
- **CoT** introduced in §3 line 97. Good.
- **SAE** introduced in §4 line 112. Good.
- **CAA / ActAdd / RepE** introduced together in §4 line 153. Good.
- **NLA** introduced in §4 line 187 with full expansion. Good.
- **AuditBench** — not really an acronym, but is named without context in §6 line 237. Glossed only by the parenthetical "(alignment.anthropic.com, March 2026)" which doesn't tell the reader what it does. **Fix**: "AuditBench is Anthropic's benchmark suite for evaluating whether alignment-auditing agents (autonomous tools that look for safety issues in production models) actually work."
- **MATS** — referenced indirectly via "Anthropic Fellows programs" elsewhere. Not in this artifact.
- **Resolution V** (§7) — explained as a technical name but the reader doesn't know there's a Resolution I-IV. Adequate as is.

### B3-10. "Why should I care?" check on section openings

- §1: opens "The plan formalizes a guess..." — passes.
- §2: opens with a "why this section" callout — passes.
- §3: ditto — passes.
- §4: ditto — passes.
- §5: ditto — passes.
- §6: ditto — passes.
- §7: ditto — passes, and is the strongest of the seven ("If you're here to decide whether the plan's contribution is real, start here").
- §8: ditto — passes.
- Conclusion: opens "The plan combines established interpretability methods..." This is an *abstract*, not a hook. **Fix**: open with the concrete take-away: "If the plan works, software teams using `pm` will get one practical thing out of it: a recipe for framing prompts that reliably produces better LLM output, with a published number for how much better."

---

## Block 4 — Prose craft

### B4-1. Paragraph-level cohesion failures

- §1 paragraph at line 53 — topic sentence: "The training-data-imitation mechanism that anchors the plan is a specialization of Andreas's framing." Paragraph body talks about human collaboration text and effort calibration. The connecting argument is implied but not explicit. **Rewrite topic sentence**: "Where does the mechanism come from? Andreas's user-modeling framing gives us the *structural* reason a next-word predictor must represent its addressee; the training-data-imitation specialization names *what* that representation is loaded with — human collaboration patterns."
- §4 paragraph at line 169 (Li 2023 / ITI): topic sentence "Kenneth Li et al., 'Inference-Time Intervention'..." starts with the citation, not the claim. **Rewrite**: "The cleanest worked example of probe-and-intervene on a non-toy variable is Li et al.'s Inference-Time Intervention (NeurIPS 2023)."

### B4-2. Paragraph-to-paragraph flow

- §3 line 93 → 95: paragraph ends "A reported 'framing beats CLAUDE.md by 4 points' means nothing if the formatting noise floor is 10 points." Next paragraph opens "There is no peer-reviewed paper that cleanly measures 'AGENTS.md/CLAUDE.md vs. nothing'..." The transition is abrupt — first paragraph is about noise floors, next is about the absence of a comparison study. **Bridge**: "The absence of a comparison study makes this worse. There is no peer-reviewed paper..."
- §5 → §6 already flagged under B2-5.

### B4-3. Sentence-rhythm

- §7 line 281–289 (the "Neighborhood" enumeration) — six bullets, each long, each structurally similar ("Closest peer on X. Same: A. Different: B."). The rhythm becomes hypnotic and the reader stops absorbing. **Fix**: vary the bullet structure — some bullets one sentence, others two; lead with a one-line summary before the same/different breakdown for the most important ones (Cabello & Neplenbroek, Choi/Transluce, Deas & McKeown).

### B4-4. Word-choice precision

- §1 line 5: "formalizes a guess working programmers make privately" — "a guess" is too casual; "formalizes" is too strong. **Rewrite**: "puts a name and a testable structure on something many practitioners have noticed."
- §1 line 22: "*Standalone novelty*: extends ... methodology to peer-ness, structured by SCM." "Standalone novelty" is jargon for review committees. **Rewrite**: "What Phase 1 contributes on its own:"
- §7 line 295: "the plan adopts whatever the model represents" — vague verb "adopts." **Rewrite**: "Phase 2 analyzes along whatever factor structure Phase 1 finds, including structures the SCM prediction did not anticipate."

### B4-5. Hedging

- §1 line 18: "*LLMs need no genuine perception of equality, only enough human collaboration text to internalize the pattern.* No claim about machine social cognition is required." — *the italicized clause* is the load-bearing one and earns its place; the follow-up "no claim ... is required" is the hedge and is redundant. **Cut the second sentence.**
- §4 line 117: "If it doesn't shift, you had a correlation, not a cause." Good — direct, no hedge.
- §7 line 295: "the plan adopts whatever the model represents, including structures the SCM prediction did not anticipate. New axes Phase 1 didn't predict — say a 'time-pressure' or 'domain-match' dimension — would be a positive finding for the plan's broader thesis, not a problem." The last clause ("not a problem") is the move-it-from-defense-to-offense — good. Keep.
- §5 line 215 closes "This makes Wang a partial pre-replication target, not just background." "Partial" is doing real work here and is correct.

### B4-6. Heavy modifiers

- §1 line 17: "enormous quantities of human-produced text" — "enormous quantities" pads. **Rewrite**: "huge volumes of human-produced text" or just "human-produced text at scale."
- §2 line 67: "measurable accuracy changes" — both adjectives can be cut to "the papers below report measured accuracy changes."
- §4 line 187: "tightly-related line of work" — "related" suffices.

### B4-7. Emphasis density

- §1 uses italics on "intellectual peer-ness," "moral peer-ness," "peer-ness," "training-data-imitation," "LLMs need no genuine perception..." within ~50 lines. The italics on "peer-ness" itself cancel each other after the third use. **Fix**: italicize the term once, the first time it appears, then drop the italics. Reserve italics for the *training-data-imitation* coinage and the no-machine-cognition sentence.
- §4 — same issue with bold names on every paper. After 16 bolded names in a table-then-prose section, the bold loses force. **Fix**: keep the bold only in the table; in the prose, use plain text for the names (the citation links carry the signal).

### B4-8. Corporate-speak / clichés

- §1 line 17: "no claim about machine social cognition is required" — fine.
- §7 line 281: "The novelty of the plan's hypothesis... is best seen by enumerating the adjacent published work." "Adjacent" here is used precisely (variables adjacent to peer-ness). Keep.
- Conclusion line 363: "The coverage gaps in this review remain..." — "coverage gaps" is mild corporate-speak but defensible. Keep.

---

## Step 5 — Citation graph walk

### Seeds (8)

1. **Cabello & Neplenbroek 2025** (arXiv:2505.16467) — closest peer on probe-user-rep + steer + measure-output-effect
2. **Choi/Transluce 2025** (user-modeling) — closest peer on user-attribute decoding
3. **Persona Vectors / Chen 2025** (arXiv:2507.21509) — closest model-own-traits peer
4. **Deas & McKeown 2025** (arXiv:2510.08915) — closest SCM-linear-probe peer
5. **Zou 2023 RepE** (arXiv:2310.01405) — methodology backbone
6. **Park 2024** (arXiv:2311.03658) — formal probe-and-steer protocol
7. **Vennemeyer 2025** (arXiv:2509.21305) — sycophancy decomposed
8. **Persona Selection Model** (Marks/Lindsey/Olah, alignment.anthropic.com Feb 2026) — post-training persona-selection mechanism

### Walk results (last-12-months Scholar filter + search-beyond-arXiv)

**Seed 1 (Cabello)**: forward — paper is recent (EMNLP 2025); citing-by literature is thin but ACL Anthology hosts the camera-ready and an OpenReview discussion exists. No 2026 follow-up found that adds prior art the lit review misses. Backward — references reach Sclar 2024, Cabello's own earlier work; no prior-art gap surfaced.

**Seed 2 (Choi/Transluce)**: forward — paper is on transluce.org, not arXiv, and citing literature is sparse there. The artifact already cites this and locates it correctly. No misses surfaced.

**Seed 3 (Persona Vectors)**: forward walk surfaces **"The Assistant Axis: Situating and Stabilizing the Default Persona of Language Models"** (Christina Lu, Jack Gallagher, Jonathan Michala, Kyle Fish, Jack Lindsey — Anthropic + MATS, arXiv:2601.10387, January 15 2026). The Assistant Axis paper extracts activation directions corresponding to character archetypes and finds the "Assistant Axis" as the leading component of persona space. Steering toward Assistant reinforces helpful behavior; steering away increases drift to other characters. The variable probed is **model-side** (the model's own Assistant-persona direction), not user-side. **This is parallel to Persona Vectors and complements §5's model-side-trait axis discussion.** It is *not* prior art that preempts the plan's user-side claim, but it is recent and on-topic enough to add. **Proposed addition** to §5 alongside Persona Vectors / Ibrahim: "Lu et al. 2026 (Assistant Axis) identify the leading activation direction of persona space as the Assistant Axis itself — steering toward it stabilizes helpful behavior, away from it triggers drift to non-Assistant characters. Same side of the causal arrow as Persona Vectors and Ibrahim (model-own-traits); the Assistant-Axis dimension is the canonical model-side anchor for any user-side probe to control against."

**Seed 4 (Deas & McKeown)**: forward — paper is camera-ready EMNLP 2025; ACL Anthology accessible; no significant 2026 citing literature. Backward — references include Fiske/Cuddy work the artifact already cites. No miss.

**Seed 5 (Zou RepE)**: forward — heavily cited; recent citing work continues to extend the contrast-pair recipe. No specific paper surfaced that the artifact misses on the user-side axis.

**Seed 6 (Park 2024)**: forward — citing literature continues on the formal-geometry side. Recent **"Non-Linear Representation Dilemma"** (OpenReview 2025/2026) extends the linear-representation hypothesis to non-linear settings — relevant to Hernandez 2024's caveat. **Proposed minor addition** to §4 alongside Hernandez: "More recent work (OpenReview 2025/2026, 'The Non-Linear Representation Dilemma') further constrains the cases where linear-probe-and-steer recipes will fail."

**Seed 7 (Vennemeyer)**: forward — paper is recent; thin citing literature. No new sycophancy-decomposition paper surfaced.

**Seed 8 (PSM, Marks/Lindsey/Olah)**: forward — the artifact already cites PSM. The Assistant Axis paper (Lu et al. 2026) is mechanistically downstream of PSM and surfaces via this seed as well.

### Walk additions (proposed)

- **Lu et al. 2026, "The Assistant Axis"** (arXiv:2601.10387, Anthropic + MATS, January 15 2026) — add to §5 model-side-traits cluster and to §7's neighborhood enumeration ("model's own Assistant persona, as a leading activation direction").
- **"The Non-Linear Representation Dilemma"** (OpenReview 2025/2026) — minor addition to §4 alongside Hernandez 2024 as a recent constraint on the linearity assumption.

Neither preempts the plan's contribution. Both should be added for completeness; neither requires re-narrowing.

### Walk coverage report

Seeds walked: 8. Date range: last 12 months emphasized, but the artifact is recent (May 2026 artifact dating) so the walk surfaces very recent (Jan–Feb 2026) work. Beyond-arXiv coverage: Anthropic Alignment Science, transformer-circuits.pub, transluce.org, ACL Anthology, OpenReview all checked via search. **Net result**: one substantive addition (Assistant Axis), one minor addition (Non-Linear Representation Dilemma). No prior art surfaced that requires re-narrowing the contribution claim. This is a *positive convergence signal* — the citation graph is approximately closed under the artifact's current set of seeds, with only adjacent-but-non-preempting work appearing in the most recent six-month window.

---

## What prior cycles missed (cross-reference appendix)

I read the prior cycle review files (CYCLE_1 through CYCLE_7) only after drafting the independent review above. Cross-references:

- **Cycle 7** caught the Assistant Axis paper independently and the artifact appears to have absorbed several of its findings, but the Assistant Axis is not yet cited in the artifact body or references. Confirming Cycle 7's finding here.
- **Cycle 7 / CITATION_GRAPH_WALK_USERMODEL.md** were thorough on the user-side-vs-model-side distinction. The contribution-narrowing through Cabello & Neplenbroek / Choi / Deas & McKeown is well-executed.
- **No prior cycle surfaced B1-1's three alternative mechanisms** (register-matching, high-status-interlocutor rule, RLHF-policy bypass) cleanly. Cycle 6 and Cycle 7 touch on register matching obliquely but don't enumerate the three as direct disambiguation targets for Phase 3. **This is a substantive miss across cycles.**
- **No prior cycle surfaced B1-4 cleanly** (Wang's "authority" is SCM-competence and the partial-pre-replication framing overstates the distinction). Cycle 6 cited Wang as a constraint; none scrutinized the construct-equivalence question.
- **No prior cycle surfaced B1-5** (multiple-comparisons / power) cleanly. Procedurally borderline (lit-review vs. plan) but worth flagging.
- **Several prior cycles flagged accessibility issues B3-1 to B3-10**; the artifact has clearly improved but residual jargon (residual-stream, linear-probe, fractional-factorial, calibration's two meanings) survives.
- Cycle 6 and Cycle 7 produced extensive accessibility findings; my Block 3 confirms most are still partially open.

---

## Summary

**Substantive findings**: 6 (B1-1 alternative mechanisms; B1-2 Phase 4 evidence-bar consequence; B1-3 Goodwin factor-retention rule; B1-4 Wang authority/competence construct equivalence; B1-5 multiplicity; B1-6 contamination foregrounding).

**Structural findings**: 5 (B2-1 §4 length; B2-2 glossary split; B2-3 §7 position; B2-4 conclusion punts the residual; B2-5 §5→§6 bridge).

**Accessibility findings**: 10 sub-areas with multiple sub-findings each, mostly residual jargon plus four dense-paragraph splits plus four concrete-example proposals.

**Prose findings**: 8 sub-areas, mostly phrasing nits.

**Citation graph walk**: 8 seeds, both directions, last-12-months filter, beyond-arXiv pass. Two additions surfaced: Assistant Axis (Lu et al. 2026, substantive) and Non-Linear Representation Dilemma (minor). Neither requires re-narrowing the contribution claim.

Overall verdict: the artifact has converged substantively. Block 1 findings B1-1, B1-2, B1-4, B1-6 are real and worth addressing in a response cycle. B1-3 and B1-5 are methodologically narrow. Block 3 still has work, especially around the residual-stream / linear-probe / fractional-factorial vocabulary and the calibration-overload. Block 4 is mostly nits.
