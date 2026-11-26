# Block 4 Review — Literature Review: User-Modeling as a Lever on LLM Performance

Scope: prose craft only. Substance, structure, and accessibility are out of scope.

## Paragraph-level findings

### Finding P1 — Introduction opener strings three ideas together

**Before** (line 5):

> The plan in `pm/plans/plan-66d430f.md` rests on a guess that almost every working programmer who uses an LLM has made privately at some point: the model seems to do better when you treat it like a colleague than when you bark a task at it.

The sentence carries (a) the plan exists, (b) it rests on a folk observation, and (c) the folk observation has a particular shape. The "almost every... privately at some point" hedge is overcooked, and "seems to do better" is the kind of hedge Block 4 hunts.

**After**:

> The plan in `pm/plans/plan-66d430f.md` formalizes a guess working programmers make privately: the model does better when you treat it like a colleague than when you bark a task at it.

(Cuts "rests on," "almost every," "who uses an LLM," "at some point," "seems to." Sharper subject-verb. Keeps the colleague/bark contrast intact.)

### Finding P2 — Peer-ness gloss paragraph buries the definition under throat-clearing

**Before** (line 9):

> A note on the central term before going further. *Peer-ness* — how much the model perceives the user as an equal partner, in the same way a colleague perceives another colleague as a fellow professional rather than as a client or a beginner. This review uses peer-ness to mean two top-level dimensions of the model's internal representation of the user: (a) *intellectual peer-ness* — whether the model judges the user as a thinking partner of comparable capability, and (b) *moral peer-ness* — whether the model judges the user as someone engaging in good faith and worth treating with respect. Throughout this review, peer-ness is the model's running judgment of the user, not a property of the user themselves.

Two openings ("A note on the central term before going further" + "*Peer-ness* —") collide. The "in the same way a colleague perceives another colleague as a fellow professional" simile sprawls. The (a)/(b) split repeats what the bullets immediately below say. The final clarifying sentence is necessary, but its weight is diluted by the dependent clauses preceding it.

**After**:

> *Peer-ness* names the model's running judgment of the user — how much it treats the user as a colleague rather than as a client or a novice. The term has two top-level dimensions: *intellectual peer-ness* (does the model judge the user as a thinking partner of comparable capability?) and *moral peer-ness* (does it judge the user as engaging in good faith and worth respecting?). Peer-ness is a property of the model's representation, not of the user.

### Finding P3 — §1 third paragraph (SCM passage) reads as a sentence-by-sentence justification with no through-line

**Before** (line 47):

> The two-meta-axis structure the plan posits for the addressee representation — intellectual peer-ness and moral peer-ness — is not a free invention. It maps directly onto the **Stereotype Content Model (SCM)** ... The SCM is the canonical social-psychology result that human perceivers cluster their judgments of others on two meta-dimensions: **competence** and **warmth**. It has been replicated across cultures and decades. The plan's *intellectual peer-ness* maps onto SCM's competence dimension; *moral peer-ness* maps onto SCM's warmth dimension. SCM gives the plan's two-meta-axis IV structure a cross-disciplinary empirical anchor rather than leaving the partition as bare intuition.

"is not a free invention" → "maps directly onto" → "is the canonical result" → "has been replicated" → "maps onto" → "gives the plan ... a cross-disciplinary empirical anchor": six successive declarative claims, each rebutting the same imagined objection (that the partition is arbitrary). The repetition signals an edit-by-committee seam.

**After**:

> The two-meta-axis structure is not a free invention. It maps onto the **Stereotype Content Model (SCM)** of Fiske, Cuddy, Glick & Xu (2002) and Cuddy, Fiske & Glick (2008), which finds across cultures and decades that human perceivers cluster judgments of others on two dimensions: **competence** and **warmth**. The plan's *intellectual peer-ness* tracks SCM's competence; *moral peer-ness* tracks its warmth. The mapping gives the partition a cross-disciplinary anchor rather than leaving it as intuition.

### Finding P4 — Phase 4 in introduction mixes claim and motivation in one sentence

**Before** (line 25):

> **Phase 4** — transfer to closed models via output-token readout of the peer-ness vector, calibrated against the open-model probes from Phase 1. This is what makes the result useful for production systems whose weights are not accessible.

"This is what makes" is a low-pressure construction. The "whose weights are not accessible" relative clause is a circumlocution.

**After**:

> **Phase 4** — transfer to closed models by reading the peer-ness vector out of output tokens, calibrated against the Phase 1 open-model probes. Closed models hide their weights; this is what makes the result usable in production.

### Finding P5 — §5 opening paragraph repeats the same contrast three times

**Before** (line 161):

> The first thing to be clear about: **sycophancy is the LLM's behavior toward the user, not a component of the plan's independent variable.** The plan's IV is what the LLM *perceives about* the user (...). Sycophancy is what the LLM *does* (agrees more readily, hedges less carelessly, drops pushback). They sit on opposite sides of the causal arrow: peer-ness is the LLM's representation of the user, sycophancy is a property of the LLM's output toward the user.

The "behavior vs. perception" point is asserted four times (bold sentence, "perceives about," "does," "opposite sides of the causal arrow"). One statement, well-placed, would carry it.

**After**:

> First: **sycophancy is what the LLM does to the user, not what it perceives about the user.** The plan's IV (competence, honesty, good faith, effort, reasonableness, respect) is on the perception side of the causal arrow; sycophancy (agreement, weakened pushback, careless hedging) is on the behavior side. The plan predicts they relate downstream: high peer-ness should produce *less* sycophancy, because the model trusts the user enough to push back. That is a side effect the plan predicts, not a component of the IV.

### Finding P6 — Conclusion's "Where the plan diverges" paragraph runs long and loses the spine

**Before** (line 293):

> Where the plan diverges: the prior framing-effects literature shows that *some framing* moves performance but does not measure which internal variable carries the effect. The prior interpretability literature probes one variable at a time — sentiment polarity, refusal, truth, the model's own emotions, character emotions, generic user demographics — but no published work probes peer-ness as a meta-dimensional *structure* (intellectual × moral, with named sub-dimensions on each meta-axis). The plan unites the two lines: take the interpretability stack and point it at the variable the framing-effects literature implies should exist, with the structure SCM predicts.

The sentence "The plan unites the two lines" is the load-bearing one and arrives last, after a long enumeration. Move it up; let the enumeration support it.

**After**:

> Where the plan diverges, it unites two lines the prior literature keeps separate. The framing-effects work shows that *some framing* moves accuracy but never measures which internal variable carries the effect. The interpretability work probes one variable at a time — sentiment polarity, refusal, truth, the model's own emotions, character emotions, generic user demographics — but never peer-ness as a meta-dimensional *structure*. The plan points the interpretability stack at the variable the framing literature implies must exist, structured the way SCM predicts.

### Finding P7 — §7 "What the plan is and isn't claiming" paragraph after the bullets does five jobs

**Before** (line 233):

> Given this neighborhood, the plan's novelty narrows from "first to probe a user-modeling variable" (which Choi/Transluce has partly established) to: **first to probe peer-ness as a meta-dimensional structure** — coordinated probing of intellectual peer-ness (competence, effort, reasonableness) and moral peer-ness (honesty, good faith, respect) as the two meta-axes that, in human relationships, predict willingness to invest care in collaboration. The variable structure (two meta-axes with named sub-dimensions, anchored on Fiske/Cuddy SCM) is the specific contribution. Phase 1 extends Choi's user-attribute decoding methodology to that structure; Phase 3 escalates to causal mediation.

Re-states the contribution three times (the bold phrase; the variable-structure recap; the phase-by-phase recap). Sub-dimension lists are repeated from §1.

**After**:

> Given that neighborhood, the plan's novelty narrows from "first to probe a user-modeling variable" (which Choi/Transluce partly establishes) to **first to probe peer-ness as a meta-dimensional structure**: two meta-axes (intellectual, moral) with named sub-dimensions, anchored on the SCM. Phase 1 extends Choi's methodology to that structure; Phase 3 escalates to causal mediation.

## Sentence-level findings

### Finding S1 — Hypothesis blockquote rhythm

**Before** (line 7):

> *The more an LLM perceives the user as an intellectual and moral equal, the higher the quality of the LLM's work. The cause is that LLMs emulate humans, and humans work better when they perceive their collaborator as an equal.*

"The cause is that" is buried-verb syntax — a nominalization plus copula where one verb would serve. "perceive their collaborator as an equal" repeats "perceives... as an... equal" from the prior sentence almost verbatim.

**After**:

> *The more an LLM perceives the user as an intellectual and moral equal, the better its work. The mechanism: LLMs emulate humans, and humans work better when they respect their collaborator.*

### Finding S2 — Pre-emptive throat-clearing

**Before** (line 18):

> The plan's prediction follows directly from the training process: *LLMs do not need to have genuine perception of equality; they need only to have read enough text where humans collaborate to have internalized the pattern.*

Three "have"s in the second clause. "need only to have read enough text ... to have internalized" is a stretched infinitive plus perfect form chain.

**After**:

> The prediction follows from the training process: *LLMs need no genuine perception of equality, only enough human collaboration text to internalize the pattern.*

### Finding S3 — Buried verb in §1

**Before** (line 45):

> The cleanest theoretical statement is **Jacob Andreas, "Language Models as Agent Models" ...**: a model trained to predict the next word in human-written text has a structural reason to represent who is writing it.

"has a structural reason to represent" is nominalized.

**After**:

> The cleanest theoretical statement is **Jacob Andreas, "Language Models as Agent Models" ...**: a next-word predictor trained on human-written text has structural reason to model who wrote it.

### Finding S4 — §2 vague verbs

**Before** (line 65):

> The sentences add no task-relevant information; they only shift social framing.

This one is clean; flagged here for contrast with the next.

**Before** (line 71):

> **Ameet Deshpande et al. ... reports that persona assignment can multiply toxicity up to six-fold over the no-persona baseline.

"Persona assignment can multiply toxicity" is fine, but "(For scale: if the no-persona baseline is roughly one toxic response in fifty, a six-fold multiplier is roughly one in eight.)" reads as arithmetic explained mid-paragraph. Tighten:

**After**:

> ... can multiply toxicity up to six-fold (roughly one toxic response in eight vs. one in fifty).

### Finding S5 — §3 awkward main-clause/subordinate-clause inversion

**Before** (line 87):

> This is load-bearing context for the plan: any A/B between framing variants and instruction-document baselines must be reported as a *distribution* over formatting variants, not a single number.

"This is load-bearing context" is a low-pressure throat-clear. The load-bearing claim is in the colon clause.

**After**:

> The implication is load-bearing: any A/B between framing variants and instruction-document baselines must be reported as a *distribution* over formatting variants, not a single number.

### Finding S6 — §4 awkward run-on

**Before** (line 137):

> Park et al. give the formal counterfactual statement: probe directions (read by linear classifiers) and steering directions (added at inference) are mathematically connected via a non-Euclidean inner product respecting language structure (distances in the model's internal representation space aren't always computed the standard way; a weighted version sometimes captures the structure better).

A parenthetical inside another parenthetical, both expanding a noun phrase. The reader has to hold three nested layers.

**After**:

> Park et al. give the formal counterfactual statement: probe directions (read by linear classifiers) and steering directions (added at inference) are connected through a non-Euclidean inner product on the representation space — i.e., distances aren't measured the standard way; a weighted version fits the structure better.

### Finding S7 — §4 Arditi sentence dragging context

**Before** (line 149):

> **Andy Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" (NeurIPS 2024, arXiv:2406.11717)** is the most striking recent demonstration: across thirteen open chat models up to 72B parameters (72 billion parameters — roughly the size of Llama-3-70B, mid-sized by 2026 standards; Claude Opus and GPT-5 are larger), one refusal direction such that erasing it makes the model stop refusing harmful prompts and adding it makes it refuse innocuous ones.

The clause "one refusal direction such that erasing it makes the model stop refusing harmful prompts and adding it makes it refuse innocuous ones" has no main verb; it's a noun phrase masquerading as a sentence. Also the parenthetical-inside-parenthetical (72 billion / Claude / GPT-5) interrupts.

**After**:

> **Andy Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" (NeurIPS 2024, arXiv:2406.11717)** is the most striking recent demonstration. Across thirteen open chat models up to 72B parameters (mid-sized by 2026 standards — Claude Opus and GPT-5 are larger), one direction governs refusal: erase it and the model stops refusing harmful prompts; amplify it and it refuses innocuous ones.

### Finding S8 — §5 "The lesson:" sentence

**Before** (line 71):

> The lesson: framing changes performance, and not always for the better, and the direction depends on which trait the framing pulls on.

Three "and"s in eighteen words.

**After**:

> The lesson: framing changes performance — not always for the better, and in directions that depend on which trait the framing pulls on.

### Finding S9 — §7 "predicted-outcome" preface sentence

**Before** (line 239):

> Listing the possible outcomes before running the experiment is called *pre-registration*. It exists to prevent the researcher from quietly tuning the analysis to match the result; the plan publishes this table before running Phase 2.

Three independent clauses split awkwardly across two sentences. The "it exists to prevent" gloss reads textbook-flat.

**After**:

> Listing possible outcomes before running the experiment — *pre-registration* — keeps the researcher from quietly tuning the analysis to fit the result. The plan publishes this table before running Phase 2.

### Finding S10 — Conclusion final paragraph

**Before** (line 301):

> References are organized by section in the bibliography at the end. Readers chasing a specific thread should treat the seed-paper list as a starting set, not a complete one.

"Organized by section in the bibliography at the end" is wordy; the bibliography is always at the end.

**After**:

> The bibliography organizes references by section. Treat the seed-paper list per section as a starting set, not a complete one.

## Word-level findings

### "Meta" vocabulary audit

`meta-dimensions`, `meta-axes`, `meta-axis`, `meta-dimensional` appear ~25 times. The prefix earns its keep in §1 and §7 where the two-tier (axis → sub-dimensions) structure is being established. Everywhere else it's a tic that could be cut to "axis" / "dimension" / "structure" with no loss.

**Cuts proposed**:

- Line 11: "internal representation of the user along these two meta-dimensions" → "internal representation of the user along these two axes"
- Line 22: "extends Choi/Transluce's user-attribute decoding methodology (§4, §7) to the specific *peer-ness* meta-dimensional structure — coordinated probing of intellectual and moral peer-ness as the meta-axes that, in human relationships, predict willingness to invest care in collaboration" → "extends Choi/Transluce's decoding methodology (§4, §7) to peer-ness specifically: a coordinated probe of intellectual and moral peer-ness, the two axes that in human relationships predict willingness to invest care in collaboration"
- Line 51: "The plan's two-meta-axis structure (intellectual + moral peer-ness)" → "The plan's two-axis structure"
- Line 233: "**first to probe peer-ness as a meta-dimensional structure**" — keep; this is the slot where the term is doing real work.
- Line 252: anchors line uses "two-meta-axis structure" twice — collapse to "two-axis structure" once.

Rule of thumb: use "meta-axis" only where you need to distinguish the top-level axis from its sub-dimensions in the same sentence. Otherwise "axis" carries the load.

### "Standalone novelty" framing audit

The phrase "Standalone novelty:" appears only once explicitly (line 22, Phase 1 bullet). Phases 2/3/4 don't repeat it. The Conclusion's "Each phase contributes independently. Phase 1 alone is a publishable... Phase 2 adds... Phase 3 adds... Phase 4 adds..." (line 297) is the parallel place — and it's clean. No repetition problem to fix. Mark as audited.

### Citation-parenthetical density

Worst offenders:

**Line 23 (Phase 1 bullet)**: "extends Choi/Transluce's user-attribute decoding methodology (§4, §7) to the specific *peer-ness* meta-dimensional structure" — only one parenthetical; fine.

**Line 47**: "**Fiske, Cuddy, Glick & Xu, "A Model of (Often Mixed) Stereotype Content: Competence and Warmth Respectively Follow from Perceived Status and Competition" (Journal of Personality and Social Psychology, 82(6), 878–902, 2002)** and **Cuddy, Fiske & Glick, "Warmth and Competence as Universal Dimensions of Social Perception: The Stereotype Content Model and the BIAS Map" (Advances in Experimental Social Psychology, 40, 61–149, 2008)**." Two giant inline citations carrying full titles and journal info inside a sentence introducing a concept. The bibliography exists for a reason.

**After**: Cut the title-and-journal data inline; trust the bibliography. "It maps onto the **Stereotype Content Model** (Fiske, Cuddy, Glick & Xu 2002; Cuddy, Fiske & Glick 2008): a canonical social-psychology result that human perceivers cluster judgments of others on two dimensions, competence and warmth."

**Line 51**: "(Goodwin, Piazza & Rozin, "Moral Character Predominates in Person Perception and Evaluation" (Journal of Personality and Social Psychology, 106(1), 148–168, 2014)" — same problem. Reduce to "(Goodwin, Piazza & Rozin 2014)".

**Line 59**: "Seminal anchors: Andreas 2022 (theoretical anchor for user-modeling); Fiske/Cuddy/Glick/Xu 2002 and Cuddy/Fiske/Glick 2008 (social-psychology anchor for the two-meta-axis IV structure, with Goodwin/Piazza/Rozin 2014 as the morality-as-separable-third-dimension alternative); Templeton 2024 ...; Kosinski 2024 / Ullman 2023 / Strachan 2024 / Shapira 2023 (the ToM dispute, background only)." — five chained citation clusters, each with parenthetical role descriptions. Reads as a footnote inflated into a paragraph. The "seminal anchors" recap at the end of every section is itself worth reconsidering for tic-status (see voice section).

### Vague verbs

- Line 41: "*Why this section.* The plan's central guess — that LLMs work better when they think the user is a peer — has both empirical and theoretical company in prior literature. This section *names* the two lines and how the plan inherits from them." — "names" is fine. But several section openers use "**looks at**" or "**walks through**":
  - Line 83: "§3 *looks at* the alternative the plan must beat" → "§3 examines the alternative"
  - Line 254: "§8 *walks through* the standard accuracy benchmarks" → "§8 surveys the benchmarks"
  - Line 37: "This review *walks the surrounding literature one topic at a time*, and at the end *places* the plan in that landscape: where it inherits, where it diverges, where it is genuinely first." — "walks the surrounding literature" is a strained metaphor; "places" is fine.

  **After**: "This review traverses the surrounding literature topic by topic, then locates the plan in that landscape — where it inherits, where it diverges, where it is genuinely first."

- Line 41 / 95 / 159 / 177 / 193 / 254: every "*Why this section.*" opener is followed by a paraphrase of "the plan needs X / this section is about whether..." Pattern check: this is fine as a structural device, but several of the body sentences after use "is about" — a near-zero-information verb.

  - Line 159: "This section is about why sycophancy is not the same thing as peer-ness, and how the plan tells them apart." → "This section separates sycophancy from peer-ness and shows how the plan tells them apart."
  - Line 177: "This section is about whether the model can be asked, in plain English, 'how do you see this user?' — and trusted to answer." → "This section asks whether the model can be queried in plain English — 'how do you see this user?' — and trusted to answer."

### Cliché audit

- "in service of" (line 278): mild cliché. "stitches together established research threads in service of one underexplored measurement" → "stitches together established research threads around one underexplored measurement"
- "robust", "comprehensive", "holistic", "leverage", "stakeholders", "going forward", "best-in-class": none found. Good.
- "load-bearing" (lines 9, 87, 99, 195, 258, 41 indirectly): the document uses "load-bearing" eight-plus times. It's a precise term in the building-trades sense and the document uses it precisely. But the frequency turns it into a tic. Cut at least two:
  - Line 87: "This is load-bearing context for the plan" → see S5 rewrite ("The implication is load-bearing") — keep this one.
  - Line 99: "The technical vocabulary used heavily below, glossed once here at first load-bearing use" — "at first load-bearing use" is jargon-on-stilts. Replace with "glossed once on first use".
  - Line 258: same phrase, same fix.
  - Line 27: "the more technical interpretability terms are glossed inline at first load-bearing use in §4 and §8" → "glossed inline in §4 and §8 where they first matter".

## Voice and tone

The document holds an academic-but-direct register throughout — generally well. Three drift points:

### V1 — Section-anchor recaps

Every section ends with a "**Seminal anchors:** X, Y, Z" line. The format is consistent but uses telegram-style fragments that contrast with the body's full sentences. Across nine sections this becomes its own register — a "footnote voice." Acceptable convention; flagging for awareness, not requiring a fix.

### V2 — Casual asides slipping into formal flow

**Before** (line 67): "OPRO ... is best known for the prompt 'Take a deep breath and work on this problem step-by-step,' which beat hand-designed prompts on GSM8K by up to 8 percentage points. The point is not that the model has lungs; the point is that some short framing tokens reliably move accuracy."

"The point is not that the model has lungs" is a casual quip in a paragraph that is otherwise formal. It's good — keep it. Flagged only because the document has few such moments and this one earns its place. Don't cut.

**Before** (line 31): "Persona prompt vs system prompt vs user message: a *persona prompt* is a sentence telling the model who it is supposed to be ('You are a senior software engineer')..." — clean, glossary register, consistent.

### V3 — First-person plural drift

The document is mostly third-person ("the plan", "this review"). One slip:

**Before** (line 112): "Different papers below clear different bars; we flag which."

**After**: "Different papers below clear different bars; the table flags which."

(There may be one or two other "we" instances — verify. Consistent third-person reads cleaner here.)

## Emphasis and modifiers

### Bold density

- Author/citation bold (e.g., "**Andy Zou et al., ...**") is used as a section-internal navigation aid. Heavy but justified once you accept the convention. No change.
- Standalone bolding inside body text:
  - Line 11: "**Intellectual peer-ness**" / "**Moral peer-ness**" in bullets — appropriate; first-use definitions.
  - Line 16: "**work quality**" — appropriate.
  - Line 18: "**training-data-imitation**" — appropriate.
  - Line 47: "**Stereotype Content Model (SCM)**", "**competence**", "**warmth**" — appropriate; introducing canonical terms.
  - Line 161: "**sycophancy is the LLM's behavior toward the user, not a component of the plan's independent variable.**" — full sentence bolded. This is the load-bearing claim of §5 and the only such sentence-bolding in the document. Keep; restraint is intact.
  - Line 233: "**first to probe peer-ness as a meta-dimensional structure**" — keep.

Density is acceptable.

### Italics

Used for term-definition (`*peer-ness*`, `*intellectual peer-ness*`, etc.), book/paper-internal titles, scare-quote emphasis ("*some* framing", "*what variable inside the model*", "*more* sycophantic"), and the hypothesis blockquote. The scare-quote italics carry weight (e.g., line 77 "*measure the internal representation that the framing manipulation moves*") and are deployed sparingly — fewer than 15 instances of pure-emphasis italics across 10K words. Within budget.

### Dashes

Em-dashes are heavily used — sometimes three in a sentence (e.g., line 51, line 47, line 233). Pattern: "X — Y — Z." This is the document's signature punctuation move, and it works most of the time, but a handful of sentences would breathe better with commas or colons.

**Audit examples**:

- Line 22: "extends Choi/Transluce's user-attribute decoding methodology (§4, §7) to the specific *peer-ness* meta-dimensional structure — coordinated probing of intellectual and moral peer-ness as the meta-axes that, in human relationships, predict willingness to invest care in collaboration." → see Meta-vocabulary rewrite (uses a colon instead).

- Line 53: "The 'humans calibrate effort by perceived peer-ness' claim is treated here as a working hypothesis the plan's result will indirectly test — not as established empirical ground truth about humans." — fine; the dash earns its keep.

- Line 251: "an effect smaller than the Sclar 2024 prompt-formatting noise floor (the §3 sensitivity result is exactly why §8 includes paraphrase-resampling); an effect that appears only in RLHF-tuned checkpoints versus base models (interesting in its own right — would suggest RLHF amplifies the human-pattern internalization)." — parenthetical inside parenthetical with dash inside. Untangle:

  **After**: "an effect smaller than the Sclar 2024 prompt-formatting noise floor — which is why §8 includes paraphrase-resampling; an effect that appears only in RLHF-tuned checkpoints, suggesting RLHF amplifies the human-pattern internalization."

### Modifiers and intensifiers

Search for "very", "really", "quite", "rather", "fairly", "somewhat":

- "rather" (line 9, 18, 45, 47, 161, 199, 219, 233, 235, 250, 272, 295): used as "X rather than Y" construction throughout — legitimate, not an intensifier. No cuts.
- "very": one instance, line 65 ("This is very important to my career") — inside a quoted prompt. Untouchable.
- "quite", "really", "fairly", "somewhat": zero or near-zero. Clean.
- "directly" (line 17, 45, 47, 153): often padding. "follows directly from the training process" → "follows from the training process" (line 18). "maps directly onto" (line 47) → "maps onto" (line 47).

## Clichés and deadwood

Cuts ranked by punch returned per word removed:

| Phrase | Location | Cut to |
|---|---|---|
| "before going further" | Line 9 | (delete) |
| "in the same way a colleague perceives another colleague as a fellow professional rather than as a client or a beginner" | Line 9 | "rather than as a client or a novice" |
| "at some point" | Line 5 | (delete) |
| "almost every working programmer who uses an LLM" | Line 5 | "working programmers" |
| "is what makes the result useful for production systems whose weights are not accessible" | Line 25 | "makes the result usable in production, where weights aren't accessible" |
| "This is what makes" (anywhere) | passim | replace with the verb being avoided |
| "The first thing to be clear about:" | Line 161 | "First:" |
| "as far as a search surfaces" | Line 89 | (delete or "to our knowledge") |
| "would be the first published comparison if it lands a real measurement" | Line 89 | "would be the first published comparison" |
| "in service of" | Line 278 | "around" |
| "the more technical interpretability terms are glossed inline at first load-bearing use" | Line 27 | "the more technical interpretability terms are glossed where they first matter" |
| "all of the well-studied ones" | (verify; "many of the well-studied ones do" line 110) | keep; this one is fine |
| "exists to prevent the researcher from quietly tuning the analysis to match the result" | Line 239 | "keeps the researcher from quietly tuning the analysis to fit the result" |
| "the relationship of that judgment to work quality" | Line 278 | "and how it relates to work quality" |
| "References are organized by section in the bibliography at the end" | Line 301 | "The bibliography organizes references by section" |

Hedging audit:

- "seems to do better" (line 5): cut to "does better" (the rest of the document argues this; hedging on it in the lead is timid).
- "may possibly", "might possibly", "tends to", "appears to": one or two instances of "appears to" / "tends to" — search and confirm; replace with confident verbs where the document elsewhere argues the claim.
- "roughly" (line 65, 71, 147, 149, 153): appropriate in scale-anchor passages; keep.

## Multi-cycle rewrite seams

### Seam 1 — Introduction's peer-ness gloss (lines 9–18)

The block (a) defines peer-ness, (b) splits it into bullets, (c) re-defines the IV, (d) gives the DV, (e) gives the mechanism. The mechanism paragraph (line 18) re-says "the plan's prediction follows directly from the training process" after the bullets have already said the same. The redundancy between line 9 ("This review uses peer-ness to mean two top-level dimensions...") and lines 13–14 (the bullet definitions) is the clearest committee-seam: two passes wrote the same definition and neither was deleted.

**Recommended fix**: cut line 9's parenthetical (a)/(b) split; let the bullets do that job. See P2 rewrite.

### Seam 2 — §1 SCM-vs-Goodwin passage (lines 47–51)

The block makes the same move three times:
1. Line 47: SCM gives the partition an anchor "rather than leaving the partition as bare intuition."
2. Line 49: warmth-terminology note clarifying what warmth means.
3. Line 51: Goodwin alternative, with the plan's two-axis structure as a "*starting hypothesis*," with phase 1 doing exploratory factor analysis, and "the plan is not committed to two-meta-axes; it is committed to *whatever structure the model actually represents.*"

The defensive "the plan is not committed" sentence reads as a Cycle-N response to a Cycle-(N-1) reviewer asking "what if SCM is wrong?" Now that the answer is on the page, it can be tightened.

**Recommended fix**: see P3 rewrite. Compress the warmth note into a clause inside the main paragraph. Compress the Goodwin alternative into "Goodwin et al. 2014 propose morality as a separable third dimension; Phase 1's factor analysis lets the data decide between two-dim and three-dim views."

### Seam 3 — §7 "Phase 1 alone is a publishable contribution" sentence (line 235)

Appears at the end of a paragraph that already says "Phase 1's contribution is the *map of structure*", and is restated almost verbatim in the Conclusion (line 297, "Phase 1 alone is a publishable map of peer-ness in LLMs"). The repetition is a seam where the §7 rewrite and the Conclusion rewrite each added the same reassurance independently.

**Recommended fix**: keep the Conclusion statement; delete the §7 one (or compress to "Phase 1 alone publishes the map; Phases 2–4 compound the contribution"). Avoid saying it twice ten paragraphs apart.

### Seam 4 — Phase descriptions (lines 22–25)

Phase 1's bullet runs ~70 words and ends with "**Standalone novelty:**..." continuing for another long clause. Phases 2/3/4 are 20–30 words each. The imbalance reads as Phase 1 having absorbed the bulk of multi-cycle additions. Trim Phase 1:

**Before** (line 22):

> **Phase 1** — probe for the model's user-equality representation along the two meta-axes. Establish that intellectual peer-ness and moral peer-ness (with their sub-dimensions) are decodable from the residual stream. Standalone novelty: extends Choi/Transluce's user-attribute decoding methodology (§4, §7) to the specific *peer-ness* meta-dimensional structure — coordinated probing of intellectual and moral peer-ness as the meta-axes that, in human relationships, predict willingness to invest care in collaboration.

**After**:

> **Phase 1** — probe for the user-equality representation along the two axes. Establish that intellectual and moral peer-ness (and their sub-dimensions) are decodable from the residual stream. *Standalone novelty*: extends Choi/Transluce's decoding methodology (§4, §7) to peer-ness, structured by SCM.

(Loses the "in human relationships, predict willingness to invest care in collaboration" gloss — but that argument is the entire opening section and doesn't need recapping in a one-line Phase bullet.)

## Overall verdict

The document is well-written by Block 4 standards. The voice is consistent, the academic-direct register holds, emphasis is restrained, and there are no egregious clichés or corporate-speak. The strongest prose is in §4 (the steering-vector catalog), where the table-then-discussion structure gives the sentences something concrete to do, and in §5 (the sycophancy distinction), where the writing has the urgency of a real argument. The weakest prose is in the Introduction (overworked from multi-cycle rewrites; the peer-ness gloss and SCM passage carry visible seams), in the Phase-bullet block (asymmetric lengths, Phase 1 over-stuffed), and in the §1 SCM-vs-Goodwin paragraph (three re-statements of the same defensive move). A focused copy-edit pass targeting these specific passages — not a whole-document sweep — would lift the document one notch. Findings count is moderate (~30 distinct rewrites across paragraph/sentence/word levels). A follow-up edit pass is warranted but should be bounded: 60–90 minutes of targeted editing on the Introduction, the SCM passage, Phase bullets, and the "meta-" vocabulary cuts. Beyond that, returns diminish quickly — the document is closer to ready-to-ship than to needs-a-rewrite.
