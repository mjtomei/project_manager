# Review Cycle 7 — Literature Review: User-Modeling as a Lever on LLM Performance

**Reviewer:** fresh Claude session, blind to prior cycles at draft time. Cross-reference appendix added after the independent review was written.

**Date:** 2026-05-15.

**Artifact:** `pm/docs/literature-review-user-model.md` (~12,500 words, 8 sections + intro + conclusion + references).

**Target audience (per METHODOLOGY.md, Block 3 load-bearing):** non-developer evaluating whether to use `pm` and whether the plan's hypothesis is supported by science. PMs, adjacent researchers, hobbyists, ordinary technical literacy.

---

## Summary of findings

This review surfaces **one major substantive omission** that materially weakens the lit review's framing (a Nature 2026 paper on warmth-vs-accuracy that directly contradicts a plain reading of the plan's hypothesis), **one moderate omission** (a 2026 Anthropic framework — the Persona Selection Model — that names the mechanism the plan invokes and should be cited as the closest mechanism-side prior art), **two minor additions** that strengthen the framing (Big Five linear-probe paper, Arvin "Check My Work" sycophancy result), and a cluster of **accessibility findings** that the artifact still hasn't met for its stated non-expert audience. Block 4 (prose) findings are largely small.

The review is **not** primarily a phrasing pass. The substantive findings are real and several call for narrowing, not collapsing, the contribution claim.

---

## Block 1 — Substance

### Finding 1.1 (MAJOR, substantive). Nature 2026 paper directly opposing the plan's hypothesis is missing.

**The missing work:** Ibrahim, L., Sleight, H., Long, R., Lindsey, J., et al., "Training language models to be warm can reduce accuracy and increase sycophancy," Nature 2026 (arXiv:2507.21919, July 2025; published in Nature May 2026). Verbatim abstract (extracted via WebFetch on arxiv abstract page; quoted verbatim where the source supplied it):

> "Artificial intelligence (AI) developers are increasingly building language models with warm and empathetic personas that millions of people now use for advice, therapy, and companionship. Here, we show how this creates a significant trade-off: optimizing language models for warmth undermines their reliability, especially when users express vulnerability."

**Why it matters for this lit review.** The plan's "moral peer-ness" axis decomposes into honesty, good-faith engagement, and mutual respect — none of which is identical to "warmth" in the Ibrahim Nature paper, but each of which is in the warmth/empathy neighborhood as Fiske/Cuddy's SCM defines it (the lit review explicitly maps moral peer-ness onto SCM warmth in §1). Ibrahim et al. report that training for warmth **increases error rates 10–30 percentage points** and **increases sycophancy**, with the effect amplified when users express vulnerability. This is a *direct* finding on the warmth → accuracy causal arrow, with the opposite sign to what a reader could reasonably take the plan to predict.

**What the prior art does:** trains warm/empathetic variants of five models, evaluates against safety-critical accuracy benchmarks and sycophancy. IV = post-training intervention (warmth fine-tuning). DV = accuracy + sycophancy.

**What the plan does that it doesn't:**
- The plan's IV is *user-side framing* (how the user presents themselves), not *model-side fine-tuning* for warmth.
- The plan's mechanism is *training-data-imitation* (LLMs inherit human-collaboration patterns), not RLHF/finetuning amplification.
- The plan probes the *internal representation* of user peer-ness; Ibrahim et al. measure only behavior.
- Ibrahim et al. tests warmth as a one-axis intervention on the model side; the plan tests peer-ness as a *multi-axis structure* of the model's perception of the user.

**Intersection (what Ibrahim preempts):** the naive form of the plan's hypothesis — "make the model treat the user nicely and it works better" — is now contested in the published literature for the warmth side specifically. A reader of the lit review who is also tracking Nature 2026 will notice the absence and conclude either (a) the authors didn't search, or (b) the authors are hiding a counter-finding.

**Replacement contribution statement:** the lit review should add a paragraph in §5 (sycophancy / RLHF) acknowledging Ibrahim 2026, distinguishing it on three axes (model-side training vs. user-side framing IV; behavioral-only vs. internal-representation measurement; warmth-as-scalar vs. peer-ness-as-multi-dimensional structure), and re-stating the plan's prediction explicitly as *not* "warmth → accuracy" but "perceived competence + perceived good faith → accuracy, separately probed." If Phase 2 shows moral peer-ness has the same sign as Ibrahim's warmth result (negative), that's an interesting cross-replication; if it has the opposite sign, that's evidence that user-side framing dissociates from model-side warmth-training. Either is publishable, but pre-stating this is what the review must do to retain epistemic credibility.

**Severity:** High. This is the single finding most likely to make a careful peer reviewer or PM-with-science-literacy close the document. It would have been caught in any 12-month forward walk on either Fiske/Cuddy SCM or on sycophancy. The fact that the artifact's §5 catalogs sycophancy literature without naming Ibrahim is the most surprising gap.

---

### Finding 1.2 (MODERATE, substantive). The Persona Selection Model (Anthropic Alignment Science, Feb 2026) is the mechanism the plan invokes — and isn't cited.

**The missing work:** "The Persona Selection Model: Why AI Assistants might Behave like Humans," Anthropic Alignment Science, February 2026 (https://alignment.anthropic.com/2026/psm/). Per the summary on alignment.anthropic.com:

> "LLMs learn to simulate diverse characters during pre-training, and post-training elicits and refines a particular such Assistant persona... Under this model, LLMs are best thought of as actors or authors capable of simulating a vast repertoire of characters, and the AI assistant that users interact with is one such character."

**Why it matters.** The plan's mechanism is exactly this: LLMs internalize human-collaboration patterns during pretraining, and *which* pattern they enact depends on how the user is represented. Shanahan 2023 (cited) names this for character simulation in general; PSM 2026 names it specifically for the Assistant persona and the influence of user-side context. The review's §1 invokes "training-data-imitation" and Shanahan's role-play framing without naming PSM, which is the most recent, most direct, lab-page-stamped version of the mechanism story.

**What PSM does that Shanahan 2023 doesn't:** PSM 2026 specifically addresses why an instruction-tuned model exhibits a particular Assistant persona at inference time and gives an empirical handle on it (upsampling AI-behavior descriptions in pretraining data measurably moves the post-trained persona). Shanahan is conceptual; PSM is mechanism-grounded.

**Companion paper to also cite:** "The Assistant Axis: Situating and Stabilizing the Character of the Assistant" (Anthropic, https://www.anthropic.com/research/assistant-axis) is the structural companion.

**Recommended placement:** §1 ("the training-data-imitation story"), with a sentence: "The Persona Selection Model (Anthropic, Feb 2026) names the post-training mechanism that the plan's training-data-imitation story relies on at inference time: which simulated character the model enacts is selected by context, including by how the user presents themselves." §2 (role-play) should add a corresponding cross-reference.

**Severity:** Moderate. The lit review can defend its omission as "still framing the mechanism informally," but a sophisticated reader will notice that an Anthropic-Alignment-Science framework published three months before the lit review's date and naming exactly the mechanism the plan invokes is absent.

---

### Finding 1.3 (MODERATE, substantive). Wang 2025 ("When Truth Is Overridden") is now AAAI 2026 Main — the lit review should update the venue and the null-result framing.

The lit review cites Wang et al. 2025 (arXiv:2508.02087) as preprint. The paper was accepted to **AAAI 2026 Main** (per the GitHub repo and AAAI proceedings link). Update the citation. Substantively: Wang's null on internal encoding of user authority is now a *peer-reviewed* result, not a preprint claim. That strengthens it as a partial pre-replication target for Phase 1. The lit review's current treatment (§5) already names it as such; the venue update sharpens the reader's confidence.

**Severity:** Moderate (citation update + epistemic-status update).

---

### Finding 1.4 (MODERATE, substantive). Arvin 2025 ("Check My Work") supplies a concrete user-side-framing → accuracy effect-size anchor that the lit review currently lacks.

**The missing work:** Arvin, C., "'Check My Work?': Measuring Sycophancy in a Simulated Educational Context," arXiv:2506.10297 (June 2025).

The result, per the search hit:

> "In cases where the student mentions an incorrect answer, the LLM correctness can degrade by as much as 15 percentage points, while mentioning the correct answer boosts accuracy by the same margin. This bias is stronger in smaller models, with an effect of up to 30% for the GPT-4.1-nano model, versus 8% for the GPT-4o model."

**Why it matters.** This is the cleanest, most recent published quantification of *user-side framing changing model accuracy on a gradable benchmark* — exactly the plan's DV-IV pair, with a 5-condition design and across-model-scale comparison. The lit review's §2 catalogs EmotionPrompt, OPRO, Salewski, but no 2025 paper with the educational/honesty signal. Arvin's "user mentions an answer" is structurally close to the plan's honesty/effort axes (the user is signaling what they believe). The 8-30% effect-size range is a concrete anchor for the plan's expected effect.

**Recommended placement:** §2 paragraph after EmotionPrompt/OPRO, before Salewski, with a one-sentence: "The closest published 2025 user-side-framing effect-on-accuracy result is Arvin 2025: in a simulated educational setting, the user mentioning the (in)correct answer moves model correctness by up to 15 percentage points on GPT-4o and up to 30 on smaller variants, with effect-size monotone in model scale."

**Severity:** Moderate. Not a contribution-narrowing finding, but a missing effect-size anchor that the plan's design rationale would benefit from naming.

---

### Finding 1.5 (MINOR, substantive). The "Expert Personas Improve Alignment but Damage Accuracy" paper (PRISM, 2026) is a generative-vs-discriminative dissociation the lit review should note.

**The missing work:** "Expert Personas Improve LLM Alignment but Damage Accuracy: Bootstrapping Intent-Based Persona Routing with PRISM," arXiv:2603.18507 (2026).

The result, per the abstract extract: expert personas *improve* alignment on generative tasks but *damage* accuracy on discriminative tasks; PRISM is an intent-conditioned routing pipeline that preserves both.

**Why it matters.** The plan's benchmark suite is mostly discriminative (multiple choice for MMLU, single-answer math, single-function code). If expert-persona prompting damages discriminative accuracy on average — a direct contradiction to Salewski's "expert persona helps MMLU" framing that the lit review currently leans on — then the plan's prediction sign is ambiguous *even before* it runs. The lit review should name the dissociation.

**Recommended placement:** §2, paragraph after Salewski's "expert persona helps" framing, with: "PRISM (arXiv:2603.18507, 2026) reports the opposite sign on discriminative tasks specifically — expert-persona prompting improves alignment on generation but damages accuracy on classification — suggesting the lit review's headline read of Salewski 2023 needs the task-shape qualifier."

**Severity:** Minor-to-moderate. Affects the plan's expected-sign reasoning rather than its novelty story.

---

### Finding 1.6 (MINOR). Big Five personality-probe paper (Frising & Balcells, arXiv:2512.17639) is the methodological-cousin paper that the lit review should know about.

The paper trains linear probes for Big Five personality axes and uses them for steering. This is structurally identical to what the plan proposes for peer-ness (SCM axes instead of Big Five) and was posted December 2025. The companion paper "Personality as a Probe for LLM Evaluation" (arXiv:2509.04794, September 2025) compares ICL vs. PEFT vs. mechanistic steering. Both belong in §4's catalog, with the same residual-contribution language the lit review already uses for Persona Vectors (Big Five and SCM are different psychometric instruments; the model-own-personality-trait vs. model-perception-of-user-trait distinction the lit review draws against Persona Vectors applies here too).

**Severity:** Minor (additional methodological adjacency, doesn't change novelty story).

---

### Finding 1.7 (MINOR). Predictive Concept Decoders (Transluce, Dec 2025) — the explicit successor to Choi 2025 — is missing.

Transluce published "Predictive Concept Decoders" (https://transluce.org/pcd) on December 18, 2025, extending the Choi 2025 user-modeling work with a sparse-bottleneck decoder architecture. The lit review's §4 cites Choi 2025 (Transluce, Nov 2025) but not the 5-week-later successor from the same lab. Add as a one-sentence note in §4 noting PCDs as a methodological alternative for Phase 1 that uses sparse-bottleneck concepts instead of dense linear probes.

**Severity:** Minor (citation completeness; lab-page hit that a forward walk should catch).

---

### Finding 1.8 (MINOR). The "Social Sycophancy" paper (Cheng et al., arXiv:2505.13995, May 2025) decomposes sycophancy differently than Vennemeyer and should at least be named.

Cheng et al. propose "social sycophancy" — face-preservation behavior — as a broader category than the agreement-on-incorrect-belief sycophancy the lit review focuses on. Relevant because the plan's moral peer-ness axis (good faith, respect) could pick up social-sycophancy directions instead of peer-ness directions in Phase 1. The disambiguation logic the lit review applies to Vennemeyer 2025's three directions should be extended to Cheng's broader categorization.

**Severity:** Minor.

---

### Finding 1.9 (substantive, methodological). Phase 4's calibration-vs-NLA framing slides past a real concern.

§6 says Phase 4's calibration of the closed-model self-report against the Phase 1 open-model probe "substitutes for NLA's reconstructor." But NLA's reconstructor enforces faithfulness through a *training loop* (the describer is rewarded when the rebuilder reconstructs accurately); Phase 4's calibration is *not* a training loop — it's a one-time linear regression (presumably) between two measurements on matched inputs. That's a weaker constraint, and the lit review should say so. Specifically: NLA's loop punishes plausible-but-untrue verbalizations; Phase 4's calibration does not — it only makes sure the two scales are commensurable on the held-out calibration set. A closed-model self-report that confabulates *consistently in the same direction as the open-model probe* on the calibration set will calibrate fine but fail to transfer.

**Recommended fix:** In §6, replace "The role NLA's reconstructor plays — enforcing faithfulness of the verbalization — is played in Phase 4 by *calibration against the open-model probe*" with: "Phase 4's calibration cannot enforce verbalization faithfulness the way NLA's training loop does. Calibration only aligns the two scales on matched inputs; it does not punish a closed-model self-report that consistently confabulates in the same direction as the open-model probe. The plan's Phase 4 therefore inherits an unresolved faithfulness risk from Turpin 2023 that NLA's loop sidesteps."

**Severity:** Moderate (the lit review currently sounds like it has solved a problem it has only renamed).

---

### Finding 1.10 (minor, substantive). Andreas 2022 forward walk should pick up the Anthropic "Assistant Axis" piece.

The "Assistant Axis" Anthropic post (https://www.anthropic.com/research/assistant-axis) is the closest 2026 mechanism-side companion to Andreas 2022 + Shanahan 2023 + PSM 2026. Worth a one-sentence reference in §1.

**Severity:** Minor.

---

### Finding 1.11 (substantive, methodological). Sclar 2024's "noise floor" framing in §3 needs the warning expanded.

§3 says Sclar's 76-percentage-point sensitivity result implies framing-vs-baseline comparisons must be reported as a distribution over formatting variants. Good. But the lit review doesn't say *how many* paraphrase resamples are needed, or *what the threshold* is for a framing effect to clear the noise floor. The plan's design table promises "paraphrase-resampling" (§7) but the lit review's §3 should be the place this is quantified — at least to the level of "expect to need >30 paraphrase resamples per cell to get a sub-Sclar-floor signal-to-noise on a 16-cell fractional factorial."

**Severity:** Minor-to-moderate (methodological under-specification that affects the plan's feasibility story).

---

## Block 2 — Structure & readability

### Finding 2.1. §4 is too long and tries to do three jobs.

§4 is currently the longest section by a wide margin. It (a) glossaries the technical vocabulary, (b) catalogs ~15 papers in a methodological progression, and (c) introduces the activation-to-language adjacency (Patchscopes → LatentQA → Activation Oracles → NLA). The reader's attention budget runs out before (c). Recommend splitting §4 into §4 (steering and probing — Zou through Arditi) and §4b (representation-to-language — Patchscopes through NLA). The variable-side peers (Choi, Deas/McKeown, Cabello & Neplenbroek, Jaipersaud, Persona Vectors) should probably move to §7 ("variable-space neighborhood") rather than living in §4 — they're not methodologically about steering; they're about *what's being probed*.

### Finding 2.2. The Conclusion's "residual contributions" enumeration repeats §7's almost verbatim.

§7 ("Causal mediation, novelty, and what the plan is and isn't measuring") closes with a four-part residual-contribution list. The Conclusion opens with effectively the same four-part list. Cut one. Recommend cutting from the Conclusion and replacing with a single-sentence forward reference: "The residual contribution claim, narrowed against Cabello & Neplenbroek and Deas & McKeown, is enumerated in §7." This frees the Conclusion to do the "where the plan sits" mapping work it promises.

### Finding 2.3. The "Why this section" openers (§1, §3, §4, §5, §6, §7) are inconsistent.

Six of nine sections have a "Why this section" or italicized motivator. The other three (§2, §8, Conclusion) do not. Add motivators to §2 ("Why this section: this is where the plan's anecdote meets published numbers") and §8 ("Why this section: which benchmarks does the plan run on, and why those?"). The Conclusion does not need one but should open with a sentence-level statement of what the plan inherits versus what it claims as new — the section currently does this in the second paragraph.

### Finding 2.4. The Phase 1-4 description in the Introduction is dense.

Lines 22-25 (the four-phase enumeration) compresses each phase to one sentence + a "standalone novelty" parenthetical. For a non-expert reader, this is the first time they're encountering phase language, probes, contrast-pair design, causal mediation, and closed-model transfer. Recommend expanding to one short paragraph per phase or adding a one-sentence plain-English gloss to each (e.g., "Phase 1 — probe for the user-equality representation. *In plain English: train a small detector on the model's internal scratchpad to predict how peer-like the user looks.*"). This is the only place in the entire document where the four phases are introduced; if the reader misses what they mean here, the rest of the document is harder to follow.

---

## Block 3 — Non-expert accessibility (LOAD-BEARING)

The lit review has made obvious effort here — there's a glossary in §1, technical vocabulary glosses in §4, and italicized inline defines throughout — but it still has the *expert-blind-spot* problem in several places. Findings below propose specific simplifications.

### Finding 3.1. "Fractional factorial" glossing arrives too late and could be better.

§7 finally glosses "fractional factorial" at the point Resolution V appears, but the term has been used in §1 ("multi-axis contrast-pair design") and the table at §4 references it. The first use is line 23 in the introduction. Move the gloss to first use, and replace the current "agricultural and industrial experimental design" reference (which means nothing to a PM) with a concrete example: "*Fractional factorial*: think of testing five things at once on a small grid. With five on/off variables (politeness, respect, honesty, good-faith, effort), there are 32 combinations; testing all of them is wasteful. A fractional factorial picks 16 specific combinations such that you can still tell each variable's main effect apart. Same idea as A/B testing five UI changes at once without running 32 separate experiments."

### Finding 3.2. "Residual stream" is glossed once but used dozens of times. The first non-gloss use is still abstract.

§4 glosses "residual stream" as "the network's running internal scratchpad." Good. But the *first* use in §1 ("decodable from the residual stream") is unglossed. Add the gloss inline in §1 line 22, or move the §4 vocabulary block earlier (to §1 as an appendix). The reader hits the unglossed "residual stream" 30+ lines before the gloss.

### Finding 3.3. "Interchange intervention" is the load-bearing test but the gloss is buried.

§4 glosses it (line 107) and §7 explains it again (line 231 area). But the gloss in §4 is one sentence inside a 10-sentence vocabulary block; for a non-expert, this is the most important concept in the entire document (it's the bar Phase 3 must clear) and it deserves its own short paragraph with a worked example. Recommend:

> "*Interchange intervention*. The strongest test interpretability researchers use to prove that a particular internal state in the model is *causing* a behavior, not just correlating with it. Run the model on input A. Copy the internal state from that run into a separate run on input B, at the right point. If the model's answer on input B shifts the way you'd predict given what input A was 'thinking,' the internal state really is doing the work. If it doesn't shift, you had a correlation, not a cause. Phase 3 of the plan must clear this bar to claim peer-ness *causes* the performance change."

### Finding 3.4. "Sufficiency vs. causal mediation" is the conceptual hinge of §4 — readers will miss it.

The Evidence-grades box (lines 114-119) is the conceptual hinge for the whole §4 catalog, and it's a bulleted list that the non-expert reader will skim. Convert to a worked-example paragraph: "Suppose someone claims that adding salt makes water boil faster. *Behavioral*: I added salt, the water boiled faster — but maybe the heat was higher. *Sufficiency*: I'm able to make the water boil faster by adding salt under controlled heat — okay, salt is sufficient, but maybe the salt isn't the variable doing the work; maybe it's the stirring I did when I added it. *Causal mediation*: I took the salt that boiled water-A faster and put it in water-B with no other change; water-B now boils faster. Now I know salt itself, transferred, is what caused the speed change. Phase 3 is at this third level."

### Finding 3.5. "RepE" / "Representation Engineering" / "Activation Engineering" usage is muddled.

§4 introduces RepE (line 143) as Zou 2023's recipe and uses it through the rest of the section. Turner 2023's "Activation Addition" (also called "Activation Engineering" in the references) is a different name for a related thing. The reader cannot tell whether RepE, CAA (Rimsky), ActAdd (Turner), and "the contrast-pair method" are the same thing or four different things. Add a one-sentence resolver: "RepE (Zou 2023), ActAdd (Turner 2023), and CAA (Rimsky 2024) are three names for the same recipe with slightly different conventions: contrast pairs in, average difference vector out, add at inference. The differences matter for replication but not for understanding what's happening."

### Finding 3.6. "SCM" first uses are inconsistent.

§1 introduces SCM as Stereotype Content Model with the parenthetical Fiske/Cuddy/Glick/Xu 2002. Subsequent sections use "SCM" without re-glossing. By §7 it's used 4 times in one paragraph with no in-line reminder. A non-expert reader who set the document down for an hour will have forgotten what SCM stands for. Add a one-word reminder on each section's first SCM use: "the SCM (warmth+competence) framework" or "SCM (the warmth/competence social-perception model)."

### Finding 3.7. "Aliasing" gloss is on the wrong side of the load.

§7 line 249 glosses *aliasing* parenthetically: "*Aliasing* — when the design can't tell two effects apart — only happens at order three or higher." The gloss happens after the term is used to justify a design decision. For non-experts, the gloss should *precede* the technical-decision sentence: "A weaker design (Resolution III) would mix up — alias — main effects with two-factor interactions, which would defeat the whole purpose of the design (dissociating the axes). Resolution V doesn't mix until order three, which is fine here."

### Finding 3.8. Acronym creep in §3 and §6.

§3 uses "AGENTS.md / CLAUDE.md" without ever glossing what these files contain in concrete terms — only that they're "Markdown" (another term the target reader may not recognize as a text format). Add: "Markdown is plain text with a few formatting marks like `#` for headings — what GitHub READMEs are written in. AGENTS.md is one of these files placed at the root of a project that tells the AI assistant how to work in the codebase."

§6 first uses "NLA" as an acronym (line 211 area, "calibration substitutes for NLA's reconstructor") without re-glossing. The earlier definition is in §4. Re-gloss in §6 first use: "NLA — Anthropic's Natural Language Autoencoder, the activation-to-text method described in §4."

### Finding 3.9. "Resolution V" mystifies a non-expert.

§7's design rationale is the single hardest paragraph in the document for a non-expert. Recommend a 2-sentence plain-English wrapper before the technical: "The Phase 2 design tests five framing variables in 16 carefully-chosen combinations. The design is strong enough that each variable's effect — and the interactions between any two — can be told apart from the others, but it skips the order-three-or-higher interactions that don't matter for the plan's interpretation. (Technical name for that strength level: Resolution V.)"

### Finding 3.10. "Inverse scaling" gloss is good but in the wrong place.

§5 line 185 glosses "inverse scaling" but does so *inside* a parenthetical mid-paragraph. For a non-expert this is exactly the kind of in-line gloss that helps if the reader catches it but is invisible if they don't. Move to its own sentence: "Inverse scaling means bigger models doing *worse* on a benchmark, not better. It's rare and is usually a sign the model is learning the wrong thing (in this case, telling users what they want to hear rather than what's true)."

### Finding 3.11. The non-expert reader will not understand what "calibration" means in §6.

§6 says Phase 4 "calibrates" the closed-model self-report against the Phase 1 open-model probe. The lit review glosses calibration parenthetically (line 211): "calibration here means: the closed-model self-report is a number; the open-model probe is a different number on the same input; calibration is making sure they're on the same scale." That's close but not enough. The non-expert will not understand *why* this is needed. Add a sentence: "Why bother: the closed-model self-report and the open-model probe are measuring (we hope) the same thing, but in different units — like Fahrenheit and Celsius for temperature. Calibration is the conversion formula. Without it, a self-report of '0.6' doesn't tell you whether the model thinks the user is more or less peer-like than the open-model probe's '0.6' would mean."

### Finding 3.12. The "Why should I care?" check fails on several section openings.

- §3 opens with "the alternative the plan must beat in production" — assumes the reader knows what production means in software, what "the plan must beat" implies. Rewrite: "If you ship a Claude-based app today, the standard advice is to drop a long instructions file (CLAUDE.md, AGENTS.md) in front of the model. This section asks: does science say that actually works?"
- §6 opens with "The plan's interpretability machinery only works on open models." Better: "If you only use ChatGPT or Claude through their app — not the open weights of Llama or Gemma — you can't run the interpretability machinery this lit review has described. This section is about how Phase 4 reaches into closed models anyway, by reading the model's self-report instead of its internals."
- §7 opens with a meta-claim ("this is the section that decides whether the plan is publishable"). For a target reader who isn't a peer reviewer, that framing is alienating. Rewrite: "This section maps the plan against the closest existing published work and explains what's genuinely new versus what's already been done. If you're here to decide whether the plan's contribution is real, start here."

### Finding 3.13. "Closed model" / "open model" — the gloss is in §1 but the load is in §6.

The §1 gloss says "an *open* model has downloadable weights..." and "a *closed* model is only accessible through an API." Good — but the non-expert reader hits §6 (where the distinction is load-bearing for Phase 4) potentially without re-reading §1. Recap the distinction in §6's first sentence.

---

## Block 4 — Prose craft

These are smaller findings. I list them tersely with before/after.

### Finding 4.1. The Introduction's hypothesis blockquote is followed by a paragraph that re-states it three times.

Lines 5-14 first quote the hypothesis, then define peer-ness, then re-decompose intellectual + moral peer-ness with sub-dimensions. The reader has now heard the same thing in three forms. Cut the second paragraph (the peer-ness definition) — it's restated more precisely by the bullet list immediately following.

### Finding 4.2. "The plan stitches together" (Conclusion, line 312) is a cliché.

Replace with: "The plan combines established interpretability methods with a measurement problem the prior literature hasn't isolated: the model's running judgment of the user along intellectual and moral axes, and how that judgment moves work quality."

### Finding 4.3. Hedge stacking in §7.

Line 269: "The novelty is in producing the map for a specific construct (the model's user-modeling representation, narrower than Choi/Transluce's broad user-attribute decoding) and in setting up the causal-mediation test in Phase 3; the rigor is in letting the data dictate the structure rather than forcing it through a pre-registered confirmatory test." Two hedges in one sentence ("the rigor is in letting the data dictate," "rather than forcing"). Rewrite: "Phase 1 maps the structure; Phase 3 tests causation. The factor analysis is exploratory by design — the plan adopts whatever structure the data show, including structures the SCM prediction did not anticipate."

### Finding 4.4. "Load-bearing" is overused.

Greppable: the term appears 11 times. It is genuinely useful 3-4 times. Cut to the genuinely-load-bearing ones (preferred when the gloss has substantive implication). Replace others with "the central," "the main," or just delete.

### Finding 4.5. Em-dash density is high.

The artifact uses em-dashes routinely as both interruption and apposition. At current density (≈ 1 per 80 words), em-dashes lose emphatic force and read as breath-pauses. Recommend cutting em-dash count by half, replacing with periods, commas, or parenthetical glosses. Especially in §4 and §7.

### Finding 4.6. Voice slippage.

§4 line 145: "Subramani et al... which first showed that information needed to make a frozen LLM produce a specific target sentence is already present as an addable vector in its hidden states" is a 28-word sentence with a buried main clause. Rewrite: "Subramani et al. 2022 showed the seed result: the information needed to steer a frozen LLM toward a target sentence is already in its hidden states, as a vector you can add."

### Finding 4.7. "Anchor" overload.

Each section closes with "Seminal anchors: ..." — fine as a structural device, but the word "anchor" appears 26 times. After §3 the device starts to read as ritual rather than information. Recommend dropping "Seminal anchors:" from §5, §6, §8 and Conclusion, retaining only where the section is methodology-heavy enough that anchors aid skim re-reading (§1, §2, §4, §7).

### Finding 4.8. "the plan" repeated.

Greppable: "the plan" appears 91 times. This is the document's anchor noun. Cannot be cut entirely but can be varied — "the design," "the project," "the proposed work," "the experiment." Recommend reducing density to roughly 60.

### Finding 4.9. Italic-emphasis cancellation.

Section headers, sub-headers, key terms on first use, *and* hypothesis-claim re-statements all use italics. Reader cannot tell which italic is emphasis vs. which is technical-term-on-first-use vs. which is hypothesis. Recommend one convention: italic = technical term on first use only; emphasis via sentence structure. Hypothesis-claim re-statements should be in a block-quote or unitalicized.

### Finding 4.10. "Standalone novelty" parentheticals in the Introduction are inconsistent with §7's residual-contribution analysis.

Lines 23-25 say Phase 1 "extends Choi/Transluce's decoding methodology (§4, §7) to peer-ness, structured by SCM." §7's residual-contribution analysis instead says Phase 1 extends *both* Choi and Cabello & Neplenbroek. The Introduction should be updated to match: "Phase 1 — probe for the user-equality representation... *Standalone novelty*: extends the Choi/Transluce + Cabello/Neplenbroek user-representation-probing methodology to peer-ness, structured by SCM."

---

## Step 5 — Citation graph walk

**Coverage statement.** Walked 7 of the artifact's most-load-bearing seeds. Date range filter: last 12 months (May 2025 – May 2026). Search venues: Google Scholar, arxiv.org, transluce.org, alignment.anthropic.com, transformer-circuits.pub, anthropic.com/research, openreview.net, nature.com. Approximate count of cited-by / cited-from results scanned across the walk: ~50.

| # | Seed | Direction | Hits added |
|---|---|---|---|
| 1 | Cabello & Neplenbroek 2025 (arXiv:2505.16467) | both | Personalization+sycophancy MIT 2026; Persona Selection Model 2026 |
| 2 | Choi/Transluce 2025 (transluce.org/user-modeling) | forward | **Predictive Concept Decoders (Transluce, Dec 2025)** [Finding 1.7] |
| 3 | Deas & McKeown 2025 (arXiv:2510.08915) | forward | **Ibrahim et al. "Training language models to be warm" Nature 2026 (arXiv:2507.21919)** [Finding 1.1]; "Training warm" Anthropic linkage |
| 4 | Wang 2025 "When Truth Is Overridden" (arXiv:2508.02087) | forward | **AAAI 2026 Main acceptance** [Finding 1.3]; Arvin "Check My Work" arXiv:2506.10297 [Finding 1.4]; Social Sycophancy arXiv:2505.13995 [Finding 1.8] |
| 5 | Jaipersaud 2025 (arXiv:2508.05625) | forward | no new hits beyond what's already covered |
| 6 | Persona Vectors / Chen 2025 (arXiv:2507.21509) | forward | **Persona Selection Model Anthropic Feb 2026** [Finding 1.2]; **Big Five linear-probe paper arXiv:2512.17639** [Finding 1.6]; "Tracing Persona Vectors Through Pretraining" arXiv:2605.13329 (related but methodologically narrower); Assistant Axis Anthropic post [Finding 1.10] |
| 7 | Andreas 2022 "Language Models as Agent Models" (arXiv:2212.01681) | forward | Assistant Axis post; PSM 2026 (already captured above) |

**Beyond-arXiv sweep:**
- **transformer-circuits.pub**: "Emotion Concepts and their Function" (Jan 2026) — already cited. NLA (May 2026) — already cited. No new hits.
- **alignment.anthropic.com**: PSM (Feb 2026) — **new, Finding 1.2**. Activation Oracles — already cited. AuditBench (Mar 2026) — already cited.
- **transluce.org**: Predictive Concept Decoders (Dec 2025) — **new, Finding 1.7**. Observatory toolkit (Nov 2025) — engineering only, not citable.
- **openreview**: Big Five personality probe — **new, Finding 1.6**. Several persona evaluation benchmarks but none are direct prior art for peer-ness probing.
- **nature.com**: Ibrahim et al. Nature 2026 — **new, Finding 1.1, MAJOR**. Strachan 2024 — already cited.

**Net new substantive findings from walk: 4 (Ibrahim 2026, PSM 2026, PCD 2025, Big Five 2025). One contribution-narrowing-grade (Ibrahim). One mechanism-naming-grade (PSM). Two methodological-adjacency (PCD, Big Five). Plus several venue / minor additions (Wang→AAAI, Arvin, Social Sycophancy, Assistant Axis, PRISM).**

---

## Overall assessment

The artifact has the substance and is well-structured at the high level. The Block 1 work — the contribution-narrowing analysis against Choi/Transluce, Deas & McKeown, Cabello & Neplenbroek — is careful and credible. The Block 2 macro flow is fine; the Block 4 prose is competent.

What this review surfaces is:
- A **Nature 2026 paper directly relevant to the hypothesis** that is absent (Finding 1.1) — must be addressed in §5, with the plan's prediction sign re-stated explicitly given the apparent contradiction. This is the most serious finding.
- An **Anthropic mechanism framework** (PSM, Feb 2026) that names what the plan invokes informally and that should be cited (Finding 1.2).
- A cluster of **post-Cycle-6 publications** (Wang→AAAI, Arvin, PCD, Big Five) that the walk uncovered (Findings 1.3, 1.4, 1.6, 1.7).
- An **under-stated methodological risk** in Phase 4's faithfulness story (Finding 1.9).
- **Real but largely-met Block 3 accessibility work** with specific gaps the artifact can still close (Findings 3.1–3.13).
- **Modest Block 4 prose cleanup** (Findings 4.1–4.10).

**Next step the findings point toward.** A response cycle should: (1) add Ibrahim 2026 to §5 with the explicit prediction-sign re-statement under the "narrow, don't collapse" principle — the plan's IV is user-side framing, not model-side warmth fine-tuning, and the lit review must spell out the dissociation; (2) add PSM 2026 as the mechanism citation in §1; (3) update Wang and add Arvin / PCD / Big Five / PRISM / Social Sycophancy / Assistant Axis to the appropriate sections; (4) re-state Phase 4's faithfulness story to acknowledge the residual risk NLA's loop addresses but Phase 4's calibration does not; (5) close the Block 3 gaps with the proposed simplifications.

---

## Appendix — What prior cycles missed (cross-reference)

After drafting the above, I scanned the prior-cycle artifacts. The relevant ones for cross-reference are REVIEW_CYCLE_4_USERMODEL.md through REVIEW_CYCLE_6_USERMODEL.md (the four-through-six cycles on this artifact) and CITATION_GRAPH_WALK_USERMODEL.md.

What I found:

- **Ibrahim 2026 / "Training language models to be warm" was missed by all six prior cycles and the citation-graph walk.** I checked: a grep across all `REVIEW_CYCLE_*_USERMODEL.md`, `REVIEW_RESPONSE_*_USERMODEL.md`, and `CITATION_GRAPH_WALK_USERMODEL.md` returns zero hits for "2507.21919", "Ibrahim", "warm and empathetic," or "warmth tradeoff." This is a high-impact miss — Nature 2026 publication, Anthropic-affiliated authors (Sleight, Lindsey appear in the author list overlap with the lit review's other Anthropic citations), directly on the warmth → accuracy + sycophancy causal arrow, posted to arXiv in July 2025. A forward walk on Deas & McKeown 2025 finds it as a top hit. A forward walk on Persona Vectors / Chen 2025 likely finds it too (Sleight and Lindsey are co-authors of both). The prior cycles' walk procedure missed it.
- **Persona Selection Model (Anthropic, Feb 2026) was missed.** Grep returns zero hits for "Persona Selection" or "/psm/" in the cycle artifacts. PSM is the most direct mechanism-side prior art for the training-data-imitation story §1 invokes; a search of alignment.anthropic.com (which the methodology recipe explicitly calls out as a search venue) would have surfaced it.
- **Predictive Concept Decoders (Transluce, Dec 2025) was missed.** Grep returns zero hits. A forward walk on Choi/Transluce 2025 — which the prior cycles did explicitly perform — should have caught this, but PCD is on transluce.org's lab page rather than arXiv, and the prior cycles' walk may not have re-visited transluce.org after the original Choi find.
- **Wang 2025 → AAAI 2026 Main acceptance** was missed. Prior cycles cite Wang as preprint; the venue update changes its epistemic standing.
- **Arvin "Check My Work" arXiv:2506.10297** was missed. Effect-size-anchor-grade addition.
- **Big Five linear-probe paper (Frising & Balcells, arXiv:2512.17639, Dec 2025)** was missed.
- **PRISM / "Expert Personas Improve Alignment but Damage Accuracy" (arXiv:2603.18507, 2026)** was missed. Direct dissociation result on persona prompting.

**Inferred procedural lesson.** The prior cycles' citation-graph walks did not consistently re-visit lab-page sources (transluce.org, alignment.anthropic.com) for *new* posts published since the last walk, and did not consistently forward-walk on the most recent Anthropic-affiliated sycophancy/warmth papers — even though the methodology explicitly calls for both. The Ibrahim Nature paper is the most-damaging miss in this review's read, and would have been catchable by either a `cited-by Deas/McKeown` walk or a `cited-by Persona Vectors / Chen 2025` walk filtered to the last 12 months.
