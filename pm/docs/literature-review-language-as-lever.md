# Literature Review: Language and Vernacular as a Lever on LLM Performance and Review

**Status:** First draft / seed for the augmented adversarial-review cycle. Citations have not been audited per `pm/docs/adversarial-review/CITATION_USE_AUDIT.md`; the audit loop is expected to verify, refine, and surface missing work. Treat all characterizations as provisional until the response file lands.

## Topic

The variation we apply to a model's *input* — what language the prompt is in, what vernacular it uses, who wrote it, what reference material the session has been primed with — is itself a lever on what the model produces. This review asks four questions that share that lever and that don't fit cleanly inside the user-modeling review (which is about the model's *internal* representation of the user; this review is about the *input variation* we can deliberately introduce).

The four questions:

1. **Adversarial review across languages and vernaculars.** Does running an adversarial-review cycle on an artifact in multiple languages and vernaculars surface different — or better, or simply more — findings than running it monolingually?
2. **Positive competence gradient by language and vernacular.** Beyond the established performance-gap framing of the multilingual / dialect-bias literature, are there tasks the model is *measurably better* at in some language or vernacular than in others (including better than English)?
3. **Native-speaker versus model-translated prompts.** When the prompt is in language X, does it matter whether it was written by a native speaker of X or produced by the model translating from English mid-session? At the response-quality level, not the translation-quality level.
4. **Session-level priming with natural-speaker reference material, with adversarial review of the prompt itself.** Within a session primed by natural-speaker reference texts in a target language or vernacular, an adversarial reviewer critiques the prompt against those references — proposing prompt changes whose justifications are anchored in specific passages of the reference material (the changes make the prompt *more faithful* to the natural-speaker register, idiom, and intent). Does iterating the prompt under this discipline change the downstream answer relative to controls?

## Why this is its own review

The user-modeling review (`pm/docs/literature-review-user-model.md`) is about how the model represents and infers users internally — the *latent* user variable. This review is about *input variation we can deliberately apply* to shift what the model produces. The two intersect at one mechanism — the inferred-user prior — but the leverages are different:

- The user-modeling review studies what the model does with whatever user it has inferred.
- This review studies how to deliberately vary the input-side signal that drives that inference, and how to discipline that variation.

A finding here that "multilingual prompting changes outputs because the inferred user differs across languages" would be a candidate **synthesis claim** for the user-modeling review; the experimental machinery and the input-side characterization belong here.

## What is known per sub-question

### Q1 — Adversarial review across languages and vernaculars

What exists is **multi-agent debate with linguistic or cultural diversity at the output-generation step**, not at the review-of-an-artifact step:

- "Multiple LLM Agents Debate for Equitable Cultural Alignment" — [arXiv:2505.24671](https://arxiv.org/abs/2505.24671).
- "Mitigating Cultural Bias in LLMs via Multi-Agent Cultural Debate" — [arXiv:2601.12091](https://arxiv.org/abs/2601.12091). Chinese setting, cross-lingual robustness via cultural personas plus multi-round deliberation; debate improves accuracy and cultural-group parity over single-LLM baselines.
- "ReViewGraph: Automatic Paper Reviewing… via LLM-Simulated Reviewer-Author Debates" — [arXiv:2511.08317](https://arxiv.org/abs/2511.08317). Paper review with reviewer-author debate, but the diversity axis is not language.

These establish that linguistic and cultural diversity in a multi-agent setting improves *output generation* and *alignment*. The specific question — *does running adversarial review of an artifact in multiple languages / vernaculars produce different or better findings than the monolingual version?* — appears to be uncovered. This is consistent with the methodology direction of "narrow the contribution, don't collapse it" (`METHODOLOGY.md`): the result that's preempted is "linguistic diversity helps in multi-agent settings," and the residual is "linguistic diversity helps *adversarial review of an artifact*, where the axis is the reviewer's frame, not the generator's."

### Q2 — Positive competence gradient by language and vernacular

The literature is dominated by the gap framing:

- "Understand, Solve and Translate: Bridging the Multilingual Mathematical Reasoning Gap" — [arXiv:2501.02448](https://arxiv.org/abs/2501.02448). Verbatim: *"performance disparities stem primarily from difficulties in comprehending non-English inputs, rather than limitations in reasoning capabilities."*
- "MindMerger: Efficient Boosting LLM Reasoning in non-English Languages" — [arXiv:2405.17386](https://arxiv.org/abs/2405.17386). Closing the gap is the framing.
- "MultiNRC: A Challenging and Native Multilingual Reasoning Evaluation Benchmark for LLMs" — [arXiv:2507.17476](https://arxiv.org/abs/2507.17476). Native multilingual reasoning, evaluation-as-gap.
- "Eliciting Better Multilingual Structured Reasoning from LLMs through Code" — [arXiv:2403.02567](https://arxiv.org/abs/2403.02567). Code as bridge across languages.

For dialect specifically, the framing is bias, not utility:

- Hofmann et al. 2024 — *AI generates covertly racist decisions about people based on their dialect* — [doi:10.1038/s41586-024-07856-5](https://doi.org/10.1038/s41586-024-07856-5) / matched-guise probing on AAVE versus SAE.
- "One Language, Many Gaps: Evaluating Dialect Fairness and Robustness of Large Language Models in Reasoning Tasks" — [arXiv:2410.11005](https://arxiv.org/abs/2410.11005). Verbatim: *"almost all of these widely used models show significant brittleness and unfairness to queries in AAVE."*
- "Side-by-side Comparison Amplifies Dialect Bias in Language Models" — [arXiv:2605.24384](https://arxiv.org/abs/2605.24384). Bias framing reinforced.

The adjacent result that points sideways at Q2 is the multilingual-prompting-for-diversity finding:

- "Multilingual Prompting for Improving LLM Generation Diversity" — [arXiv:2505.15229](https://arxiv.org/abs/2505.15229). Multilingual prompting outperforms temperature sampling, step-by-step recall, and persona prompting on diversity across GPT-4o / 4o-mini / LLaMA 70B / 8B. Mechanism attributed to language-specific knowledge activation.

Diversity is not competence, however. *"Better in some language X for some task Y, with a documented mechanism"* — that positive-direction competence claim does not appear to be established. The closest hint is the *Understand, Solve and Translate* result that reasoning capability is preserved across languages while comprehension is not — which implies the underlying competence is at least *not worse* in non-English once comprehension is controlled, but does not show positive cases.

### Q3 — Native-speaker versus model-translated prompts

- Practitioner consensus: native > machine-translated prompts, with the gap notable on machine-translated test data.
- "Lost in Literalism: How Supervised Training Shapes Translationese in LLMs" — [arXiv:2503.04369](https://arxiv.org/abs/2503.04369). Characterizes translationese as a *model output* artifact.
- "How Important is 'Perfect' English for Machine Translation Prompts?" — [arXiv:2507.09509](https://arxiv.org/abs/2507.09509). Prompt-quality effects on translation.
- "Estonian WinoGrande Dataset: Comparative Analysis of LLM Performance on Human and Machine Translation" — [arXiv:2511.17290](https://arxiv.org/abs/2511.17290). *"Model performance on human translated datasets is slightly lower than on the original English test set, while performance on machine-translated data is notably worse."*

What is **not** isolated: the same prompt issued in language X by a native speaker versus the same prompt produced by the model self-translating from an English source, with downstream-answer quality (not translation quality) as the dependent variable. That comparison is the Q3 residual.

### Q4 — Session-level priming with natural-speaker reference material, with adversarial prompt review

Adjacent literature, none addressing the design directly:

- In-context-example selection — register / style matching of in-context examples shifts behavior. Relevant but not the same thing.
- Style and dialogue accommodation — the model accommodates to a user's register, including in code-switched contexts.
- Cross-lingual prompting variants (Cross-Lingual Thought Prompting; cross-lingual self-consistency) — bring in multiple languages but for correctness, not for *prompt faithfulness against a reference corpus*.

The Q4 design as proposed combines two pieces neither of which has been studied jointly:

1. **Session-level priming with natural-speaker reference texts.** Loading the session with corpus material from native speakers of the target language or vernacular.
2. **Adversarial review of the prompt against those references.** A separate reviewer agent critiques the prompt with the discipline that every proposed prompt change must be justified by a specific reference-text passage — the change makes the prompt more *faithful* to the natural-speaker register, idiom, intent.

The faithfulness criterion is structurally the same as the citation-audit step in the augmented review cycle (`CITATION_USE_AUDIT.md`): just as the citation audit checks that what is cited is used faithfully against the source, prompt review checks that the prompt is used faithfully against the natural-speaker reference. Two faithfulness problems, same shape — the methodology surfaces a clean reuse.

## Open questions and proposed residual contributions

For each question above, the residual that survives the prior-art audit:

1. **Q1 residual:** linguistic / vernacular diversity *as a property of the reviewer ensemble* in an adversarial review of an artifact. The methodology question: does reviewer diversity along this axis surface findings that monolingual review misses, and how does the marginal benefit decay as the ensemble's linguistic diversity grows?
2. **Q2 residual:** positive-direction competence gradients across languages and vernaculars, with a mechanism. Candidate mechanisms to test: (a) cultural-prior alignment (some tasks have ground truth more strongly anchored in a non-English culture's training corpus); (b) lexical-conceptual fit (some concepts pack into shorter representations in some languages); (c) prompt-faithfulness — a native-speaker formulation in language X may be more faithful to the actual task than an English rendering.
3. **Q3 residual:** the prompt-provenance comparison, holding language constant. Native versus self-translated, response-quality as the dependent variable.
4. **Q4 residual:** the combined design — priming plus prompt-faithfulness review against references — and its measurable downstream effect on the same prompt.

## Proposed methodology for Q4

Concrete experimental shape, for the cycle to refine:

1. **Reference corpus selection.** Pick a target language or vernacular X. Assemble a natural-speaker corpus matched to the task domain (e.g., for a sycophancy-elicitation task, native-speaker informal-register text in X; for a code task, native-speaker programming-discussion text in X). Document selection criteria explicitly so the comparison is reproducible.
2. **Session-level priming.** Load the corpus into the session as reference material. Operationalize as either system-prompt context or in-context demonstrations.
3. **Prompt drafting.** Write or auto-generate an initial prompt in X for the task under study.
4. **Adversarial prompt-faithfulness review.** A separate reviewer agent — independent from the prompt-drafting agent, mirroring the agent-independence rule in `SUGGESTION_PASS.md`-style methodology — reviews the prompt against the reference corpus. The reviewer's prompt carries the discipline:
   - *Every proposed prompt change must be justified by a specific reference-text passage that the change makes the prompt more faithful to.*
   - *Faithfulness criteria are explicit: register, idiom, lexical choice, framing of the question as a native speaker of X would frame it, cultural presuppositions, conversational implicature.*
   - *Where the prompt is already faithful, the reviewer must say so explicitly (the no-change case is allowed and is itself an informative output).*
5. **Iterate.** Accept / modify / reject prompt changes per the same response-block discipline the augmented cycle uses; re-issue the iterated prompt; capture the response.
6. **Controls.** Match against (a) the same prompt in X with no priming; (b) the same prompt in X with priming but no prompt review; (c) the same prompt translated from an English original, no priming, no review; (d) the prompt in English. The four-way comparison isolates priming, review, and language-of-prompt effects.
7. **Dependent variables.** Task-specific quality measures; diversity of responses across multiple samples; faithfulness of the response to natural-speaker norms (judged by native speakers or by a separately-primed evaluation agent).
8. **The reviewer is what's new.** The combination of (a) reference-grounded adversarial review of the prompt and (b) iteration under that discipline is the novel intervention. The expected mechanism: even if the prompt's surface language is X, a model-generated or English-derived prompt carries English-conditional cues that shift the inferred user away from a native-X speaker; reference-grounded review pulls the prompt back toward the native-X conditional, and the response shifts accordingly.

## Connections to the user-modeling review

The mechanism this review hypothesizes — that the model conditions response on an *inferred user* whose attributes are read off the prompt's language, register, idiom, and reference material — is the same mechanism the user-modeling review uses for sycophancy and demand-inference. The two reviews share a synthesis claim. The contribution of this review is to treat that mechanism as a *lever* the experimenter can operate, and to characterize how to operate it (priming, faithfulness review, prompt iteration).

Conversely, results from Q4 — that reference-grounded prompt review produces measurably different responses than ungrounded prompting — would be a load-bearing piece of evidence for the user-modeling review's mechanism claim: it would show the inferred user is not just a passive correlate of the prompt's surface features but a variable the experimenter can deliberately shift.

## Audit status and next steps

This is a first-draft seed. The augmented cycle should now run on it:

- **Review** (`METHODOLOGY.md` Block 1 with the missing-citations structured format): identify missing prior art per sub-question, especially on Q4's priming-plus-prompt-review combination and on any *positive-direction* competence-gradient findings that this draft missed.
- **Citation audit loop** (`CITATION_USE_AUDIT.md`): every citation in this draft is currently `unverified` — none has had a full-text audit. The audit loop should verify each, surface scope conditions and alternative interpretations, and flag any over-characterization (in particular the Saideh et al. mechanism claim and the *Understand, Solve and Translate* "comprehension not reasoning" framing both need full-text checks).
- **Response** (`METHODOLOGY.md`): consolidate proposed changes from review and audit, with provenance tagging.
- **Walker / Apply** (`plan-litreview.md`): the walker UI is not yet implemented; until it is, decisions land directly via response file editing.

When the new-flow registry exists (per `plan-litreview.md`), this review should be registered as:

```yaml
- id: language-as-lever
  target: pm/docs/literature-review-language-as-lever.md
  target-type: file
  status: active
```
