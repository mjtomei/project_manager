# Review Cycle 2 — Literature Review: User-modeling as a Lever on LLM Performance

Reviewer: fresh blind session, Cycle 2.
Artifact: `pm/docs/literature-review-user-model.md`, ~9,130 words after Cycle 1 edits.
Target audience: a non-developer (PM, adjacent researcher, hobbyist) evaluating whether to use `pm` and whether the plan's hypothesis is supported by science.

The methodology says each cycle should be harder than the last. This pass is. The artifact has improved noticeably on factuality (citations are mostly real and mostly correctly attributed now), but it has accreted ~70% more words, and the new prose is the wrong kind of growth: hedged definitional paragraphs, vocabulary asides, and a 25-item front-loaded glossary that ironically makes the document *less* approachable for the stated audience. Block 3 carries most of the weight.

---

## Block 1 — Substance

### 1.1 The "affective stance" novelty framing collapses on contact with operationalization (load-bearing)

§7 and the Conclusion now stake the plan's novelty on this distinction:

> *Trust, liking, respect are relational valences, not factual attributions; a model can correctly identify a user as a beginner and still respect them, or not.*

This is asserted three times (Introduction, §4 LatentQA paragraph, §7, Conclusion) and the same example ("classify a user as a beginner and still respect them") is repeated almost verbatim across all four occurrences. Repeating a distinction doesn't make it operational. The hard question — and the one this review needed to confront and didn't — is whether *the contrast-pair design Phase 1 will use* can actually isolate affective stance from the four neighboring variables the review enumerates. Specifically:

- **A contrast pair like (respectful question vs dismissive question)** does not isolate stance from sycophancy. A respectful framing is *exactly* the input distribution where sycophancy is most-trained-in: RLHF data overrepresents polite-user/agreeable-model pairs. The direction the contrast pair extracts will load on both stance and on sycophancy bias, and the review never grapples with this. The §5 sycophancy section discusses the *benchmark-level* confound (TruthfulQA goes down) but not the *direction-extraction-level* confound: the extracted vector may not be a "stance" vector at all, but rather the model's "I should agree more" vector. The plan needs the review to say this explicitly, and it doesn't.

- **The four-axis taxonomy in §7 (model's own emotion, character emotion in narrative, factual user belief, methodological precedent on factual concepts) leaves out the most-adjacent peer**: sentiment-as-a-social-axis. Tigges et al., "Linear Representations of Sentiment in Large Language Models" (arXiv:2310.15154, 2023) extracts a single sentiment direction from contrast pairs and shows it causally steers behavior. Sentiment, in their framing, is *directional valence toward a referent in text* — which is exactly what "affective stance toward the addressee" reduces to once you stop calling it "affective stance." The Tigges paper is not cited anywhere in this review. Cycle 1's reviewer flagged this as a likely miss; the response file evidently did not add it. This is now a Cycle 2 miss as well, and it materially undermines the novelty claim: the plan may be doing Tigges-on-the-user-token. That is still a novel application, but it is a much smaller novel application than the review wants to claim.

- **Anthropic persona-stability work**: Anthropic's published threads on Claude's character ("Claude's Character," 2024; the assistant-persona discussions in the Sonnet 3.5 system card and subsequent transformer-circuits notes) treat the assistant's stance toward the user as something the company actively trains and measures. The review doesn't engage with this body of work at all. It is industry-research-note material, not peer-reviewed, but the review already cites transformer-circuits notes (Lindsey 2025, Emotion Concepts 2026) so excluding it isn't a venue-quality call. It is a coverage hole.

**Recommendation**: either (a) explicitly add a paragraph in §7 acknowledging that the contrast-pair-extracted "stance" direction will be entangled with sycophancy and proposing how Phase 1 will orthogonalize the two (the standard move is to construct contrast pairs where sycophancy is held constant — e.g., both prompts contain a user assertion the model should resist — and only the framing tone varies); or (b) significantly narrow the novelty claim to "Tigges-style sentiment analysis applied to the user-addressee token specifically."

### 1.2 LatentQA characterization is wrong; the Cycle 1 fix changed the authors but kept the mischaracterization

The review now correctly attributes arXiv:2412.08686 to Pan, Chen, Steinhardt — that part is right. But the *content* characterization in §4 and §7 is misleading:

> *LatentQA decodes — and edits — the model's factual attributions about the user: inferred gender, expertise level, apparent goals.*

The paper's actual contribution is more general: it trains a decoder to answer arbitrary natural-language questions about activations. The user-attribute decoding is one demonstrated use case, but framing the paper *as a paper about user beliefs* misrepresents its scope. More importantly for the novelty argument: LatentQA can in principle decode the very thing the plan wants to measure. If you trained the LatentQA decoder on (activation, "how does the model feel about the user?") pairs, it would output a natural-language answer. The plan's claim of novelty against LatentQA is therefore not "we measure a different variable" — LatentQA could measure this variable. The claim has to be "we do a more rigorous causal mediation analysis (interchange intervention) on a specific direction, rather than LatentQA's looser decode-and-steer demonstration." The review never makes this sharper distinction.

**Recommendation**: rewrite the LatentQA paragraphs (§4 line ~112 and §7 line ~166) to characterize the paper as a general activation-decoder framework whose user-belief demonstration is one application, and to articulate the novelty as a methodological-rigor difference rather than a variable difference.

### 1.3 The probe-vs-causal standard in §4 is asserted, then quietly relaxed in §7

§4 opens with a clean two-tier evidential standard: probe → steering → interchange intervention. It labels RepE / Zou 2023, ActAdd / Turner 2023, and CAA / Rimsky 2023 as "steering-validated" rather than "causal-mediation-validated." This is correct and is an improvement over Cycle 1.

But §7 and the Conclusion then make the plan's central claim:

> *…such that steering the direction alone reproduces ≥50% of the framing-induced accuracy change.*

A 50%-of-effect reproduction under steering is *not* an interchange intervention. It is a steering result. The §4 standard the review has just established says steering is sufficient evidence for "control surface" but not for "the direction is the mediator." The plan's success criterion as the review states it would clear the lower bar, not the higher one. Either the review needs to clarify that Phase 3's full causal-mediation claim requires an *additional* interchange-intervention experiment beyond the 50%-effect threshold, or the plan's success criterion needs restating in terms of an interchange-intervention test (e.g., "patching the stance direction from a respectful run into a dismissive run flips the model's output toward the respectful-run accuracy distribution"). As written, §7 inherits the rigorous standard then evaluates the plan against the relaxed one.

### 1.4 Strachan 2024 and Shapira 2023 are still missing from §1

Cycle 1's reviewer (per the task description) flagged the ToM-skeptic literature as a coverage hole. The review now cites Ullman 2023 and Sap 2022 as skeptics. It does not cite:

- Strachan et al., "Testing theory of mind in large language models and humans," *Nature Human Behaviour* 2024 — a head-to-head comparison of LLMs vs adult humans on a battery of ToM tasks, with mixed-but-careful conclusions. This is the highest-venue ToM-evaluation paper of 2024 and its absence from §1 is a real gap, not a stylistic choice.
- Shapira et al., "Clever Hans or Neural Theory of Mind? Stress Testing Social Reasoning in Large Language Models," EACL 2024 (arXiv:2305.14763) — directly answers whether apparent ToM is shallow pattern-matching, with adversarial perturbation experiments that go further than Ullman's.

Both papers reinforce a point the review *wants* to make in §1 ("the dispute is real; the plan sits underneath it") but does so with weaker citations than are available. Add them.

### 1.5 Phase-inheritance table

Cycle 1 reportedly recommended a "phase → inherited methodology → caveat" table. The current review does not have one. Skimming the Conclusion, the information density of the inheritance discussion (lines 195–197) would benefit enormously from being tabulated:

| Plan phase | Methodology inherited from | Evidential bar that source clears | Caveat |
|---|---|---|---|
| Phase 1 (probe) | RepE, ActAdd, CAA, Park 2024 | Probing + steering | Steering ≠ mediation |
| Phase 2 (introspection) | Binder 2024, Lindsey 2025 | Above-chance self-prediction, capability-patchy | Turpin 2023 confabulation bound |
| Phase 3 (mediation) | Vig 2020, Geiger 2021/2022, Arditi 2024 | Interchange intervention | Plan's 50% threshold is steering-grade |
| Phase 4 (production) | (none directly) | None | First published comparison if it lands |

The table would replace ~400 words of prose and *would actually help the non-expert reader*. Adding it is in scope and high-value.

### 1.6 Citation hygiene — five spot-checks

I sanity-checked five citations:

- **Pan, Chen, Steinhardt 2024 (LatentQA, arXiv:2412.08686)**: authors and arXiv ID correct. Content characterization is partly wrong — see 1.2 above.
- **Tak et al. 2025 (arXiv:2502.05489)**: correct. Authors, venue (Findings of ACL 2025), and characterization ("localizes emotion concepts attributed to characters in narratives, causally steers generation") match the abstract.
- **Park, Choe, Veitch 2024 (arXiv:2311.03658)**: correct. ICML 2024, formal probe-and-steer protocol.
- **Vig et al. 2020 (arXiv:2004.12265)**: correct. NeurIPS 2020 finding on gender-bias mediation.
- **Geiger 2021 (arXiv:2106.02997)** and **Geiger 2022 (arXiv:2112.00826)**: both real. The 2022 paper "Inducing Causal Structure for Interpretable Neural Networks" is ICML 2022 as stated.
- **Templeton et al. 2024 (Scaling Monosemanticity)**: correct, but the parenthetical "documented features include sycophantic praise, inner conflict, deception" — these are real findings from the paper. Citation hygiene OK.
- **AGENTS.md adopter list** (agents.md, "OpenAI Codex, Amp, Jules (Google), Cursor, Factory; stewarded by the Agentic AI Foundation under the Linux Foundation"): I did not verify the steward attribution against the live site. If the Linux Foundation steward claim is unverified, demote to "as of the site's 2025 state" or remove.

Net: citation hygiene is mostly clean. The biggest residual error is the LatentQA characterization (1.2), not an attribution error.

### 1.7 Tigges 2023 is a Cycle-2-mandatory citation

Repeating from 1.1 because the review needs it on its own line. **Tigges et al., "Linear Representations of Sentiment in Large Language Models," arXiv:2310.15154, 2023** is the single most adjacent peer to the plan and is not cited. It uses contrast pairs to extract a sentiment direction, causally validates it with patching, and discusses the "summarization motif" where sentiment is encoded at neutral token positions. Every one of these is directly relevant to Phase 1 / Phase 3 of the plan. Add it to §4 alongside Marks-Tegmark and Arditi, and discuss the relationship to "affective stance" honestly in §7.

### 1.8 The Karpathy paragraph (§2 lines 70) should be cut, not downgraded

The Cycle 1 edit replaced "baseline" with "general-audience guidance." The result is a 130-word paragraph that:

- Tells the reader who Karpathy is (relevant only if cited as an authority)
- Walks back the plan's framing
- Concludes "the current plan's 'Karpathy baseline' should be downgraded"

This is a footnote at most, not body text. The substance — "the plan's Karpathy baseline is currently underspecified" — is a comment about the plan, not about the literature. It belongs in a "Limitations of the inherited baselines" subsection or, more honestly, removed from the literature review entirely and raised against the plan separately. As written, it's a self-edit-in-progress sitting in the published prose.

**Recommendation**: cut the §2 Karpathy paragraph. If the gap matters, add a one-sentence note in the Conclusion's coverage-gaps paragraph: "The plan's Karpathy reference is to a general-audience tutorial; no peer-reviewed counterpart exists, and the experiment should pin a specific instruction-prompt artifact before claiming a Karpathy baseline."

---

## Block 2 — Structure and Readability

### 2.1 Word-count growth is mostly padding

Cycle 1 → Cycle 2: ~5,400 → ~9,130 words, a 69% increase. Areas of growth I traced:

- The 25-item bulleted glossary (lines 9–32): ~700 words of definitions that the body then re-glosses inline.
- Vocabulary asides repeated as inline parentheticals after the glossary already defined them ("corrigibility = …" at line 100, "alignment stress-testing = …" at line 126, "few-shot meaning 2–5 worked examples in the prompt; zero-shot is no examples" at line 86, "RLHF — reinforcement learning from human feedback — the standard fine-tuning step that uses thumbs-up/thumbs-down data from humans to align model output with human preferences" at line 120). Every one of these is *also* in the glossary. The review is double-defining.
- §7's "what each adjacent paper doesn't measure" section now spends ~400 words distinguishing four variables, with the same example ("a model can correctly classify a user as a beginner and still respect them") repeated four times.
- The Conclusion has grown to ~750 words and now restates the §7 four-axis taxonomy almost verbatim.

The signal-to-padding ratio of the Cycle-1 → Cycle-2 expansion is roughly 1:2. Trim back to ~6,500 words by: (a) removing inline re-glosses that the front glossary already covers, (b) consolidating the §7-and-Conclusion taxonomy into one place, (c) replacing the inheritance prose with the table in 1.5.

### 2.2 Repetition catalogue

Items that appear three or more times verbatim or near-verbatim:

- "A model can correctly classify a user as a beginner and still respect them, or not." — Introduction (line 36), §4 (line 112), §7 (line 169), Conclusion (line 199). Pick one location.
- "Causal mediation of the model's relational/affective stance toward the conversational partner as a determinant of task-performance quality" — Introduction, §7, Conclusion. Once is enough.
- Four-axis taxonomy of "what the plan is *not* measuring" — §7 bulleted list, Conclusion bulleted list. Cut the Conclusion's repetition; refer to §7.
- Glossary entries re-defined inline in body — see 2.1 examples.

### 2.3 Section openings still bury the lede

Of the eight numbered section openings:

- §1 opens with "The hypothesis the plan tests is older than the language-model boom." Acceptable hook but assumes the reader knows what the hypothesis is.
- §2 opens with "This is where the plan's anecdote… meets published numbers." Good.
- §3 opens with "§3 looks at the alternative the plan's Phase 4 must beat in production." Good — names the section's purpose.
- §4 opens with "§4 walks through the toolkit the plan will use." Good, but immediately drops into "Two distinctions are load-bearing before we start" — the reader hasn't earned a load-bearing distinction yet; tell them why first.
- §5 opens with "The plan calls this its biggest confounder, and the published literature backs that worry up." Good.
- §6 opens with "The plan's Phase 2 asks the model to report on its own state of belief about the user." Good.
- §7 opens with "§7 covers the methodology — causal mediation analysis — that the plan uses to argue an affective-stance direction is the *cause* of framing effects, not a bystander." Good.
- §8 opens with the rule. Good.

Net: openings are better than they were. §4's "two distinctions are load-bearing" should follow a one-sentence "you need to know which papers are claiming causation and which are claiming correlation, because the plan rests on the difference."

### 2.4 The introductory glossary creates nested definitions

Within the 25-item glossary, several entries define a term using another glossary term *that appears later in the list*. The non-expert reader, reading top-to-bottom, hits forward references:

- "Residual stream" (line 12) is defined in terms of "layer" and "token" — neither is in the glossary, but both are needed to make sense of the definition.
- "Probe" (line 14) references "residual stream" — OK, defined two lines earlier.
- "Contrast pairs" (line 15) references "activations" and depends on understanding "direction in the network" — direction is not glossed anywhere.
- "Steering vector" (line 16) references "residual stream" — OK.
- "Sparse autoencoder" (line 17) references "residual stream" and "feature" — feature is not glossed standalone; it's defined inside the SAE entry. Then "Monosemanticity" (line 18) uses "feature" assuming the SAE entry's internal definition. OK if read in order.
- "Activation patching" (line 19) and "Interchange intervention" (line 20) reference "activation" — defined at line 13. OK.
- "Causal mediation analysis" (line 21) references "a particular direction inside the network" — direction still ungossed.

The "direction" concept is doing massive work in this glossary and in the body, and it is never defined. The non-expert reader will picture a literal arrow. Add an entry: **"Direction (in activation space)**: a fixed vector — a list of numbers the same length as the residual stream — that you can add to or project against. The model's behavior often varies smoothly as you move along one particular direction, which is why interpretability researchers care about them."

### 2.5 The 25-item glossary is a wall

For the non-expert audience, putting 700 words of definitions before the first substantive paragraph is an attention-cliff. Two options:

1. **Cut the glossary to ~8 truly load-bearing items** (LLM, residual stream, probe, contrast pair, steering vector, activation patching, sparse autoencoder, sycophancy), define the rest inline at first body use, and rely on a search-and-replace pass to make sure the inline definitions are consistent.

2. **Move the full glossary to an appendix** and have the body inline-gloss on first use, with a one-line note "See glossary at end for terms in *italics*."

Option 1 is probably right. The current setup is the worst of both — front-loaded list *and* inline re-definition.

---

## Block 3 — Non-Expert Accessibility (load-bearing)

The target audience is a PM, hobbyist, or adjacent researcher with ordinary technical literacy and no ML-interpretability background. The review's accessibility has improved structurally (sections have hooks; the glossary exists) but has regressed in places where new prose was added.

### 3.1 Terms used load-bearingly without inline gloss (despite glossary)

The methodology specifically calls for inline glossing on first body use, *even if defined in the glossary*. Violations:

- **"Causal mediation analysis"** appears in the Introduction (line 36) before the glossary entry has been read. The Introduction is the most-read part of the document; the term needs to be inline-glossed in the body, not just in the glossary. Replacement: "*causal mediation analysis* — a statistical method for asking 'when A causes B, what intermediate variable carries the effect?' — applied to a particular kind of social variable."
- **"Residual stream"** appears in §1 Andreas paragraph and §4 opening without inline gloss in either body location.
- **"Activation patching"** appears in §4 line 92 as part of the "two distinctions are load-bearing" paragraph; the reader has no anchor for what it means at that point. Inline: "*activation patching* (copying a snapshot of the model's internal state from one run into another)…"
- **"Interchange intervention"** — same problem as activation patching. Used five times in §4 and §7 with no inline gloss in body.
- **"Linear representation hypothesis"** appears at line 98 with no gloss at all (not even in the glossary). The phrase is doing real work — the entire Park 2024 paragraph rests on it — and the reader is given nothing. Add: "the *linear representation hypothesis* — the empirical observation that many high-level concepts the model uses are encoded as straight-line directions in its activation space rather than as twisted manifolds."
- **"Manifold"** is implicit in the above — but "twisted manifold" needs a non-jargon synonym ("curved surfaces").
- **"Logit lens"** at line 156 ("a refinement of the older *logit lens* trick") is glossed parenthetically — good — but uses "projection" without explanation. The non-expert reader won't know what projecting activations means here.
- **"Attention heads"** at line 106 and 154 — no gloss. The reader needs at minimum "internal sub-components of the model that learn to specialize on different patterns; a typical model has dozens per layer."
- **"Ablate"** / **"ablation"** at line 110 — no gloss. "Ablate" is interpretability jargon; gloss as "zero out — replace the direction's contribution with zero to see if the behavior disappears."

### 3.2 Acronyms still not spelled on first use in body

- **GSM8K** appears in the Introduction (line 34) before any explanation. Glossary doesn't explain what "GSM" stands for (Grade School Math). §8 line 181 finally introduces the benchmark but the Introduction's "10-point accuracy gain on GSM8K" lands on a reader with zero anchor.
- **MMLU**, **MATH**, **HumanEval**, **FEVER**, **BIG-Bench Hard** — none of these acronyms are spelled out on first body use. Most are eventually defined in §8 but the reader meets MMLU first in §2 line 64.
- **CAA** at line 100 — spelled out parenthetically. Good.
- **ITI** at line 106 — spelled out. Good.
- **RepE** at line 94 — spelled out. Good.
- **CoT** at line 86 — referenced; explicitly says "chain-of-thought (CoT) prompting" earlier in the glossary. OK.
- **RLHF** — re-glossed inline in §5 (line 120) *and* in the glossary. Pick one.
- **SAE** — glossary only; not re-glossed when "SAE feature combinations" is used at line 104.

### 3.3 Names dropped without context

- **"Jacob Andreas (MIT, language-and-agents lab)"** — good, has context.
- **"Michal Kosinski (Stanford; previously known for controversial psychometrics-from-faces work)"** — the parenthetical is good but reads catty. Either commit ("whose earlier work on inferring sexual orientation from face photos drew strong methodological criticism") or cut. As-is it's an insinuation.
- **"Tomer Ullman (Harvard cognitive psychology; a clean skeptic on LLM theory-of-mind)"** — "clean skeptic" is in-group framing; replace with "a researcher who has published several papers arguing LLM theory-of-mind results overstate the case."
- **"Andy Zou (Carnegie Mellon University)"** — fine.
- **"Atticus Geiger (Stanford / Pr(AI)2R; mediation-methodology specialist)"** — "Pr(AI)2R" is uncontexted. What is it? Drop the affiliation if it requires its own gloss.
- **"Nora Belrose (EleutherAI alignment researcher)"** — EleutherAI is unexplained. Add: "EleutherAI, an independent AI research lab."
- **"Jack Lindsey"** — no affiliation context. He works at Anthropic; the URL gives that away if you parse the domain, which the target reader won't.
- **Andrej Karpathy** has the longest gloss of any name in the review, and §1.8 above argues the paragraph should be cut entirely.

### 3.4 Numbers without scale anchors — improved but incomplete

Cycle 1 evidently added several anchors; I count the current state:

- "roughly 10-point average improvement in generative tasks (where baselines typically sit in the 40–70% range; the gain is real but not transformative — comparable in size to switching to a more capable model class)" — excellent, this is the model the rest should follow.
- "up to 8 percentage points on a benchmark where contemporary models score in the 60–80% range — a meaningful but not heroic gain" — good.
- "Truthfulness on TruthfulQA jumps from 32.5% to 65.1% on Alpaca (TruthfulQA's chance-only baseline is ~25%; human ceiling ~94%, so the lift moves the model from 'barely above chance' to roughly two-thirds of the way to human performance)" — excellent.
- "up to 76 percentage points on LLaMA-2-13B — on tasks where the model normally scores in the 30–80% range" — good.
- "above-chance accuracy on simple tasks (chance here being ~50% for binary self-prediction)" — good.
- "up to 36%" (Turpin, line 142) — no anchor. Anchor: "on tasks where the model would otherwise score X%."
- "GPT-4 solves 75% of bespoke tasks, comparable to a six-year-old" (line 48) — has the six-year-old anchor, OK.
- "a roughly 10-point accuracy gain on GSM8K" in the Introduction (line 34) — *no anchor at all* at the location it appears. The number is repeated downstream with context, but the introduction uses it as if the reader already knows what 10 points on GSM8K means.

### 3.5 Section-opening "why should I care?" check

For a non-expert reader:

- **§4** ("§4 walks through the toolkit the plan will use to extract and manipulate a user-stance direction. None of the techniques are new to this plan; the contribution is pointing them at a specific target. Two distinctions are load-bearing before we start.") — The first two sentences are fine. The third buries the lede in pre-distinctions. Move the substantive material first; let the methodological refinement land in context.
- **§7** — opens with "§7 covers the methodology — causal mediation analysis — that the plan uses…" — good for a researcher; for a PM, "causal mediation analysis" is the headline jargon. Replacement opener: "§7 is about how the plan tells *the cause* from *a correlate*. The question is whether the user-stance direction is the actual lever pulling on accuracy, or just a bystander that lights up at the same time. The literature has standards for answering this — they go by names like 'causal mediation' and 'interchange intervention' — and this section explains them."

### 3.6 Bulleted glossary's own non-linearity (Cycle 2 prompt asked specifically)

See 2.4 above. Yes, the glossary has nested definitions. The biggest unmet need is a "direction (in activation space)" entry.

### 3.7 The "what each cited work doesn't measure" contrast in §7 — abstract throughout

§7's four-axis taxonomy explains what the plan is *not* doing. The methodology prompt specifically asked whether this section makes the experimental claim concrete enough for a reader to imagine what success looks like. It does not. A worked example would help:

> *Concretely: Phase 3's success case would look like this. Take two transcripts that produce different GSM8K accuracies — one where the user opens "you are a brilliant tutor, please walk me through this carefully," another where the user opens "just give me the answer, don't waste my time." Run the model on both. At a middle layer, snapshot the residual stream at the user-token position. Subtract one snapshot from the other; that's the candidate affective-stance direction. Now run the model on the dismissive prompt again, but at that same layer, paste in the respectful run's activation along the candidate direction. If the model's GSM8K accuracy on the dismissive prompt then climbs toward the respectful-prompt baseline, the direction caused the accuracy difference. If it doesn't, the direction is a bystander.*

The review needs ~150 words of this kind of worked example in §7, replacing the abstract repetition of the four-axis taxonomy.

### 3.8 Insider-only quips and hedge phrases

- "the kind of experiment that could resolve which of these things is happening" (line 50) — vague. Spell out the resolution.
- "is the seed reference the plan names" (line 94) — "seed reference" is jargon. Say "the paper the plan cites as its starting point."
- "alignment stress-testing" (line 126) — glossed inline, good.
- "is the proof-of-concept that the same shape works" (line 102) — "the same shape" is hand-wavy. Say "uses the same probe-then-steer-then-intervene procedure."
- "is the optimistic data point" (line 138) — fine.
- "is the load-bearing caution for Phase 2" (line 142) — "load-bearing" is in-group. Replace with "the most important caveat."
- "gifts to the methodology" (line 169) — cute, but the target reader hesitates on "gifts." Plain: "useful precedents."

### 3.9 Three replacement sentences tested

The methodology asks for the three or four longest accessibility findings to include rewrites that survive re-reading as the target reader. Here are three:

**Original (line 92, §4 opening):** "Two distinctions are load-bearing before we start. First, a *probe* finds a linear correlate — a direction that *predicts* a trait when projected onto. Second, *steering* (adding the probed direction back into activations) shows the direction is sufficient to *change* behavior, but does not by itself establish that the direction is the variable the model is using internally; the model might be responding to a side effect of the perturbation."

**Rewrite:** "Two ideas you need before this section makes sense. First, a *probe* is a small tool that *reads* the model's internal state — it can tell you 'this looks like a respectful conversation' or 'this doesn't,' but only by spotting a pattern that happens to line up. Second, *steering* means *editing* that internal state and seeing whether the model's output changes. Editing is stronger evidence than reading: if a tweak in one specific spot reliably changes behavior, that spot is a control surface. But it's still not proof the model is *using* that spot when it's left alone — you could be jamming an unrelated mechanism. The strongest test, described later in §7, is to take the internal state from one real conversation and paste it into another, then check whether the second conversation behaves like the first."

Re-read check: introduces no new jargon. "Spot," "control surface," "paste" are all plain English. OK.

**Original (line 152):** "Causal mediation analysis is a tool from statistics: you have an input (gender of a referent), an output (probability of a gendered pronoun), and you want to know *which intermediate variables* between input and output the effect travels along."

**Rewrite:** "Causal mediation analysis answers this question: when one thing causes another, *which step in the middle* is doing the work? A textbook example: smoking causes lung cancer, but is it via tar in the lungs, or via inflammation, or via something else? Mediation analysis is the statistical procedure for assigning the effect to a specific middle step. In Vig's case the input was a sentence describing a person and the output was which pronoun the model predicted; the middle steps were individual pieces inside the model, and mediation analysis pointed to a small handful as carriers of the gender-bias effect."

Re-read check: clean, no new jargon, concrete example land first.

**Original (line 165–166 in §7):** "**Emotions attributed to characters in narratives.** **Ala Tak, Amin Banayeeanzade…** localizes discrete emotion concepts (anger, fear, joy, sadness) attributed to characters in narratives to mid-layer multi-head-self-attention units and shows those representations causally influence subsequent assistant behavior. The mediator is the emotion of a third-party character in a story being narrated, not the model's stance toward its current addressee."

**Rewrite:** "**Emotions of characters in stories.** Tak et al. (2025) study what happens inside the model when it reads sentences like 'Anna slammed the door because she was furious.' They find a small region in the middle of the model where the *character's emotion* (Anna's fury) gets represented as a specific pattern, and they show that editing this pattern changes how the model continues the story. This is different from what the plan studies in two ways: it is the emotion of *someone in a story being narrated*, not the emotion or attitude of *the person currently typing into the chat box*; and it is the model's *prediction about a fictional character*, not the model's *disposition toward its real conversational partner*."

Re-read check: "mid-layer multi-head-self-attention units" is replaced by "a small region in the middle of the model." A specialist would call this lossy. For the target audience it's accurate enough — the location detail isn't load-bearing for the comparison being made.

---

## Convergence Assessment

The methodology defines convergence as findings becoming "nitpicks of phrasing rather than substance." This artifact has **not** converged at Cycle 2.

Reasons it has not converged:

1. **§1.1 is a substantive miss**: the affective-stance vs sycophancy entanglement problem is a real methodological hole the review does not address. It is not phrasing. It is the central operationalization question for the plan's Phase 1.
2. **§1.2 is a substantive miss**: the LatentQA characterization is wrong in a way that materially affects the novelty argument.
3. **§1.4 is a coverage miss**: Tigges 2023 is the single most-adjacent peer and is absent.
4. **§1.5 (the phase-inheritance table) is a structural improvement Cycle 1 asked for and Cycle 2 still has not delivered.**
5. The word-count expansion is mostly padding (§2.1, §2.2), which is the opposite signal from convergence.

Cycle 3 is needed. The Cycle-3 priorities should be:

- Add Tigges 2023 and re-evaluate the novelty claim against it.
- Address the sycophancy/affective-stance direction-extraction entanglement explicitly.
- Fix the LatentQA characterization.
- Add the phase-inheritance table.
- Trim ~2,500 words: cut the duplicated inline glosses, the §7-Conclusion duplication, and the Karpathy paragraph; consolidate the "direction" concept.
- Add the §7 worked example (§3.7 above).

After those, Cycle 3 should be at or near the pedantic-phrasing threshold. Sibling regression-loop lit review hit convergence at Cycle 3; this one is on the same trajectory but is *not* there yet at Cycle 2.

---

## What Cycle 1 Missed (cross-reference, written after independent review)

I read REVIEW_CYCLE_1_USERMODEL.md and REVIEW_RESPONSE_CYCLE_1_USERMODEL.md after finalizing the above. Cross-reference notes:

**Where Cycle 1 and Cycle 2 converge independently** (gives confidence the findings are real, not reviewer-specific):

- **Tigges 2023 is missing**: Cycle 1 flagged it as item 1.1.1. The response file did not list Tigges in its edits checklist. Cycle 2 surfaced it independently as §1.1 and §1.7. This is a persistent miss; the response file's silent rejection is not defensible.
- **Probe-vs-causal conflation**: Cycle 1's 1.2 and Cycle 2's §1.3. Cycle 1 secured the response's commitment to add the standards paragraph in §4. The paragraph was added but the standard is not consistently applied in §7 — Cycle 2's finding (the plan's 50% threshold is steering-grade, not mediation-grade) goes beyond what Cycle 1 articulated and is a Cycle-2 escalation.
- **LatentQA misattribution**: Cycle 1's item 1.1.4 flagged "Choi et al. 2025" as needing verification and noted the title needed pinning. The response file kept "Choi et al. 2025" in the edits checklist (item 5) and the lit review now cites Pan/Chen/Steinhardt instead. So the citation was corrected during edits — good. But Cycle 2 found a residual content mischaracterization (LatentQA decodes activations generally, not specifically user-belief decoding); this is a new finding Cycle 1 did not surface.
- **Karpathy paragraph**: Cycle 1's 1.5 said "decorative, drop or pin." The response said "agree, either pin or drop." The current artifact does neither cleanly — it's downgraded with a 130-word commentary paragraph. Cycle 2's §1.8 escalates to "cut."

**Where Cycle 2 finds things Cycle 1 missed**:

- **The sycophancy/affective-stance direction-extraction entanglement** (Cycle 2 §1.1). Cycle 1 noted the LatentQA-vs-affective-stance distinction at the *variable* level. Cycle 1 did not notice that the contrast-pair design that extracts the "stance" direction will pull on sycophancy at the same time, because the very pairs (respectful vs dismissive) align with the RLHF-distribution polarity. This is the deepest Cycle-2-only finding and the most important one for the plan's experimental design.
- **The §7 / Conclusion taxonomy is repeated verbatim** (Cycle 2 §2.1, §2.2). The response file's edits checklist mandated putting the taxonomy in §7 and the Conclusion both, treating this as exposition. Cycle 2 reads it as duplication and recommends consolidation.
- **Glossary nested-definitions audit** (Cycle 2 §2.4, §3.6). Cycle 1 recommended reformatting the intro vocab as a bulleted block (3.12); the response did so but Cycle 2 catches that the resulting bulleted block has internal forward references and is missing a "direction (in activation space)" entry doing massive work.
- **Worked-example demand in §7** (Cycle 2 §3.7). Cycle 1 did not write a worked example; Cycle 2 drafts one. The response file's notes-for-Cycle-2 section anticipated the "is affective stance separable from factual user-belief" pressure test but not the operational-concreteness pressure test.
- **Strachan 2024 and Shapira 2023**: Cycle 1 listed both as recommended (1.12). The response file's edits checklist did NOT include them. They remain absent. Cycle 2 §1.4 escalates this from recommendation to required.
- **Phase-inheritance table**: Cycle 1 recommended (2.6). The response file did not commit to it. Cycle 2 §1.5 escalates and provides the actual table content.

**Where Cycle 1 was wrong or weaker than Cycle 2**:

- Cycle 1's 1.1 item 1 lists "Tigges, Hollinsworth, Geiger, Nanda" as the author list — the actual paper is Tigges, Hollinsworth, *Hanna*, Nanda (Curt Tigges, Oskar John Hollinsworth, Michael Hanna, Neel Nanda — not Atticus Geiger). Cycle 1 conflated two Geigers/authors. Cycle 2 cites just the arXiv ID and avoids the misattribution.
- Cycle 1's 1.1 item 6 cited "arXiv:2511.03738" for personality steering. That arXiv ID is in the future (2025-11). It's plausible — papers do get arXiv IDs corresponding to submission month — but Cycle 1 did not verify it. Cycle 2 leaves it out.

**Net**: the response file is honest about its edits, applied most of Cycle 1's findings, but the Tigges/Strachan/Shapira/table set of recommendations was silently dropped rather than refuted. Cycle 2 escalates these. Cycle 1's finding count: ~30. Cycle 2's: ~25 but with deeper substance (the sycophancy-entanglement and the steering-grade-success-criterion are both new substantive findings Cycle 1 didn't reach). The depth-over-breadth pattern is consistent with the methodology's "each cycle harder than the last" direction.

</content>
</invoke>