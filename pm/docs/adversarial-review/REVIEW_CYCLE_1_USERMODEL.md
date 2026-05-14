# Adversarial Review, Cycle 1 — Literature Review: User-modeling as a Lever on LLM Performance

Target: `pm/docs/literature-review-user-model.md` (the artifact)
Plan being reviewed-around: `pm/plans/plan-66d430f.md`
Reviewer: blind, fresh session, no access to prior cycles.

The review structure follows `pm/docs/adversarial-review/METHODOLOGY.md`. Block 3 is the largest because the audience cannot be assumed to know any of the interpretability vocabulary the artifact uses.

---

## Block 1 — substance

### 1.1 The "strongest novelty" claim is overstated. Probably wrong.

The conclusion and §7 both rest the plan's primary novelty on "causal mediation analysis applied to a *social* variable (user-modeling) has not been done." This is the load-bearing scientific claim of the entire review, and a 30-minute citation walk finds at least three direct counter-examples the review does not cite:

1. **Tigges, Hollinsworth, Geiger, Nanda (2024-style), "Linear Representations of Sentiment in Large Language Models"** — sentiment is a social-affective variable; the paper finds a single direction, ablates it, and reports the causal effect on downstream completions. This is causal mediation on a social variable, full stop. Not cited.

2. **Mechanistic Interpretability of Emotion Inference in Large Language Models** (Findings of ACL 2025, arXiv:2502.05489 / aclanthology 2025.findings-acl.679). Directly studies emotion concepts (an "agent state" the model attributes to characters/users) as causal mediators of behavior, with the explicit framing "emotion representations causally influence the LLM's outputs … this influence drives the Assistant to behave in ways that a human experiencing the corresponding emotion might behave." This is exactly the experiment the plan claims is unprecedented, run on emotion rather than user-expertise, but the structural shape is identical. Not cited.

3. **"Emotion Concepts and their Function in a Large Language Model"** (Anthropic / transformer-circuits.pub 2026 — at the time of writing, a public note at `transformer-circuits.pub/2026/emotions/index.html`). Same shape as the plan: probe an internal emotion state, steer it, measure behavior change. Functional emotions are a social-mediator variable in everything but name. Not cited.

4. **Choi et al. 2025 — "LatentQA"-style decoders on model beliefs about the user**. Multiple recent surveys reference this work as decoding "the model's beliefs about a user." If this is correctly characterized in survey literature (verify the exact title), it directly preempts the plan's claim of being first to probe a user-belief representation. The review's citation graph walk missed it. Verify and cite.

5. **Park, Choe, Veitch — "The Linear Representation Hypothesis and the Geometry of Large Language Models"** (ICML 2024, arXiv:2311.03658). The review does not cite Park et al. at all. Park et al. is the formal statement that linear-probe directions and steering directions are causally linked (via counterfactual pairs), with experiments on LLaMA-2. The plan's "probe then steer to confirm causality" recipe is *exactly* the protocol Park et al. formalize. Omitting Park is a meaningful gap because the plan's methodological warrant rests on the linear representation hypothesis.

6. **Tan et al., "Personality Traits in Large Language Models" / activation-space personality steering work (arXiv:2511.03738 cited in surveys)**. Personality traits *of the agent* and the implied *user* model are tightly related; the multi-property steering literature is closer to the plan's hypothesis than the review admits.

**Recommendation**: rewrite §7's last paragraph and the conclusion's "where the plan is genuinely novel" section. The honest novelty is narrower: causal mediation specifically targeting a *probed user-trait belief* (not the model's own state, not the affective state of a character in a story) as the mediator of a *productivity / accuracy* effect on standard knowledge/code benchmarks. That is a real but much smaller claim than "no one has mediated a social variable."

### 1.2 The probe-vs-causal distinction is asserted but then quietly conflated.

The review correctly names the distinction (§4, Belrose 2023) but then uses "probe" and "vector" interchangeably without flagging which one is causally validated. Examples:

- §7: "varying the framing of a conversation changes accuracy … *via* a probed user-trait vector." A probed vector is by construction a correlate, not a cause. The sentence should be "via the direction the probe identifies, and only if interchange-intervention confirms causal responsibility."

- §4 lumps RepE, ActAdd, CAA, ITI, Geometry of Truth, refusal-direction together as if they're all causally validated. Several are. RepE in its 2023 form is mostly correlational — Zou et al. demonstrate behavioral changes from steering but do not run formal interchange-intervention tests on every claim. The review conflates "we added the vector and behavior changed" (steering) with "we have established the direction is the causal mediator" (mediation/interchange). These are different evidential standards. Belrose 2023 is cited *as if* it warned about this — but Belrose's actual contribution (the tuned lens) is about per-layer prediction recovery, not about the probe-vs-causal distinction. The review name-drops Belrose to validate a point Belrose did not make.

**Recommendation**: dedicate two sentences to "what counts as a causal claim here" early in §4. Cite Vig 2020 and Geiger 2021/2022 as the actual sources for the standard. Demote Belrose to its actual role: a tool for reading the model's intermediate state.

### 1.3 Andreas 2022 is doing less work than the review claims.

Verified via the arXiv abstract: Andreas 2022 is a short conceptual position paper. The review says Andreas "lays out *why* you would expect a user-modeling vector to exist if you went looking." That is roughly right, but the review treats Andreas as theoretical *backbone* and seminal anchor invoked twice. In fact, Andreas's claim is that LMs represent properties of agents *whose text they are predicting* (the author). The plan is interested in the model's belief about the *interlocutor / user / addressee* — a different agent. Andreas 2022 does support the general "LMs model agents" thesis, but does not specifically support "LMs model their conversational partner's expertise and that mediates output quality." That is an extrapolation. The review should flag the extrapolation explicitly.

### 1.4 EmotionPrompt mediation — already partly done.

The review claims "none isolate user-model as the mediating variable" for EmotionPrompt-style effects. The 2025 Findings-ACL paper on mechanistic interpretability of emotion inference (cited above, 1.1 item 2) explicitly mediates emotion-stimulus effects on output behavior. It is not literally the EmotionPrompt paper's data, but it is mediation on the same lever EmotionPrompt pulls. The plan's framing should acknowledge this — "the mediation has been done for emotion *concepts in narratives*; we extend it to emotion-and-expertise *beliefs about the user*."

### 1.5 Andrej Karpathy citation is too thin.

The review cites Karpathy's "How I Use LLMs" YouTube talk (2h11m, published February 27 2025 per Karpathy's own X post) but treats it as if it provides specific instruction-prompt patterns the plan should benchmark against. The talk is a general-audience tutorial; the plan's Phase 4 wants a *specific* prompt pattern to benchmark. The review hand-waves "should grab one specific Karpathy-popularized instruction-prompt" without naming which. If the plan wants Karpathy as a baseline, the review must extract the concrete prompt (timestamp, exact wording) or admit the citation is decorative. Right now it is decorative.

Also: the review repeatedly elides whether Karpathy is at OpenAI, Tesla, or nowhere (he was at OpenAI, then Tesla, then founded Eureka Labs and is currently independent / Eureka). Audience needs the one-line identification.

### 1.6 OpenAI April 2025 sycophancy rollback — date verified, but the artifact mischaracterizes Anthropic's response.

Verified: rollout Apr 24–25 2025; OpenAI announced rollback Apr 29 2025 at openai.com/index/sycophancy-in-gpt-4o/. There is a follow-up "Expanding on what we missed with sycophancy" (openai.com/index/expanding-on-sycophancy/). The review's date and citation are correct.

What the review does *not* do, but the original task hint suggests should be checked: there is no claim in the review that "Anthropic's response counts as a published response." Good — that fictitious claim is not present. (If you were expecting me to find one and complain, I cannot complain about something that is not there.)

### 1.7 Scaling Monosemanticity "user is upset / talking to a child" — possibly imprecise.

The review's introductory paragraph lists "the user is upset," "this text is in French," "the assistant is being deceptive" as example SAE feature interpretations from Scaling Monosemanticity. Templeton et al. 2024 *does* document features for sycophancy, deception, inner conflict, gender and racial bias, and the various known examples (Golden Gate Bridge, code vulnerabilities, etc.). I cannot directly verify the specific phrasing "the user is upset" or "talking to a child" as listed features in the paper (the artifact 403'd a direct fetch; secondary sources do not list those literal feature labels). The most-cited illustrative features from the paper are "sycophantic praise," "inner conflict," "Golden Gate Bridge," "deception," and various biases.

**Recommendation**: either pin the exact feature labels (with the section/figure of Templeton et al. 2024) or rewrite the example as "features such as 'sycophantic praise' and 'inner conflict' (Templeton et al. 2024)." Right now the illustrative example is the most evocative sentence in the introduction for the plan's hypothesis, and it might be inaccurate. That is a high-cost imprecision.

### 1.8 AGENTS.md description has a minor factual error.

Verified at agents.md: the format is described as having "emerged from collaborative efforts across the AI software development ecosystem, including OpenAI Codex, Amp, Jules from Google, Cursor, and Factory." The review says "jointly launched in 2025 by Google, OpenAI, Factory, Sourcegraph, and Cursor." Sourcegraph is not on the agents.md attribution list; Amp (Sourcegraph's tool) and Jules (Google's tool) are. Also note the format is now managed by the Agentic AI Foundation under the Linux Foundation. The review should correct attribution.

### 1.9 The plan's central testable claim — is it well-supported by prior science?

Reviewing for the audience: yes, partially. The "user-modeling representation exists" piece is well-supported by Andreas 2022 (conceptually), Sap 2022 / Kosinski 2024 / Ullman 2023 (empirically, with disputes), and the steering literature (mechanistically). The "framing changes performance" piece is well-supported by EmotionPrompt, OPRO, Salewski. The "framing → user-model → performance" chain is the novel synthesis and is supported but not yet demonstrated. The review accurately conveys this if §7 is rewritten to drop the overclaim.

### 1.10 Lindsey "Emergent Introspective Awareness" weight.

Lindsey 2025 is a research note at transformer-circuits.pub, not peer reviewed, single-author preprint-equivalent. The review cites it twice as if it were a stable empirical anchor for the plan's introspection step, while only briefly noting in the conclusion that it is "a research note." For Phase 2's design (verbalized readout calibrated against probe ground truth), Binder 2024 is sufficient; Lindsey 2025 is supplementary. The review's prominence-of-citation for Lindsey is disproportionate to its evidential weight. Demote.

### 1.11 Missing: contamination and benchmark validity.

§8 mentions contamination in one sentence at the end. Given the plan plans to use MMLU and HumanEval as headline benchmarks, this is a substantive concern that warrants more than a sentence. Recommended additional citation: **Magar & Schwartz, "Data Contamination: From Memorization to Exploitation" (ACL 2022)** and **Sainz et al., "NLP Evaluation in Trouble" or "Did ChatGPT cheat on your test?" line of work (EMNLP 2023 / 2024)**. The plan should also reckon with **MMLU-Pro (Wang et al. 2024)** as the contamination-hardened successor benchmark; the review should mention it.

### 1.12 Missing: ToM-style benchmarks more recent than 2023.

§1's theory-of-mind sub-literature stops at Ullman 2023 and Kosinski 2024. Worth at least name-checking:
- **Strachan et al. 2024 (Nature Human Behaviour)** — comparison of GPT-4 vs human ToM across multiple tasks.
- **Gandhi et al. 2024 / "Understanding Social Reasoning" line.**
- **Shapira et al. 2023, "Clever Hans or Neural Theory of Mind?"** — directly relevant skeptic.

These would harden §1.

### 1.13 The "social-variable steering literature is thin" claim is partly false.

Verified: the literature is not as thin as the review suggests. In addition to items 1.1 above, there is active work on personality steering (Activation-Space Personality Steering, arXiv:2511.03738), demographic-bias steering (multiple surveys), and the **Marks-Tegmark Geometry of Truth** which the review does cite but does not connect to "social variable" framing. The review should soften the thinness claim to "thin *specifically on user-trait beliefs as mediators of task performance*."

---

## Block 2 — structure and readability

### 2.1 Eight topic sections — too many; some should collapse.

The current layout:
1. Do LLMs model agents?
2. Persona/role/framing effects
3. System-prompt / AGENTS.md scaffolds
4. Activation steering & control vectors
5. Sycophancy & RLHF artifacts
6. Introspection & self-report
7. Causal mediation
8. Benchmarks

§3 (system-prompt scaffolds) is short and reads like a peripheral aside. It could fold into §2 as "what the practitioner baseline looks like." §8 (benchmarks) is a checklist; it could become an appendix or a closing one-pager. That gets you to six topic sections plus intro and conclusion, which is closer to the sibling lit review's structural rhythm.

### 2.2 The intro's vocabulary gloss — incomplete.

The intro glosses LLM, residual stream, probe, steering, SAE, sycophancy, activation patching, causal mediation. Good list, but several first-use terms in the body are *not* in the intro and are not glossed at first body use:

- "contrast pairs" (§4) — never glossed.
- "control vector" / "steering vector" — used interchangeably without saying so.
- "interchange intervention" (§7) — never glossed.
- "monosemanticity" (References, Templeton 2024) — never glossed, despite the paper title being load-bearing.
- "sparsity" — implicit in SAE definition but never said.
- "refusal direction" (§4) — used as if obvious.
- "RLHF" (§5) — *is* glossed inline at first use; correct.
- "CoT" / "chain-of-thought" — used in §3 without acronym expansion; expanded in §8 implicitly via Wei 2022; should be glossed on first use.
- "alignment," "alignment-stress-testing" (§5, Denison citation) — never glossed.
- "calibration" (§6) — used without gloss.
- "inverse scaling" (§5) — glossed parenthetically, OK.
- "logit lens" (§7) — name-dropped, used to define tuned lens, but logit lens itself is not explained.
- "TruthfulQA," "FEVER," "GSM8K," "HumanEval," "MMLU," "MATH," "BIG-Bench Hard" — most are glossed in §8, but §2 and §5 *use* them before §8 explains them. Forward-reference problem.

See Block 3 for the proposed glosses.

### 2.3 Conclusion's "inherits / diverges / novel" structure — the novelty paragraph is overstated, the inheritance is well-supported.

The inheritance paragraph cleanly maps each prior thread to a plan phase. Good. The divergence paragraph is honest. The novelty paragraph is the problem (see Block 1.1). Rewrite to scope the novelty claim narrowly.

### 2.4 Repetition.

"This is the plan's strongest novelty claim" appears in §7 in bold. The same claim appears in the conclusion. After Block 1.1's corrections, both should be softened, and the bold should come out — bold the *correct* novelty claim (narrower, more defensible) instead.

### 2.5 Headings.

"§3 System-prompt and AGENTS.md style scaffolds" mixes the abstract concept (system prompt) and the specific spec (AGENTS.md). Rename: "Instruction scaffolds: system prompts, CLAUDE.md, AGENTS.md."

### 2.6 Missing figure or table opportunity.

A single table mapping plan phases → primary inherited methodology → seminal citation → caveat would replace much of the conclusion's prose and would help the audience track the dependency structure. The review is otherwise prose-heavy.

Suggested table columns:
- Phase
- What the phase does (one sentence)
- Inherited from (one citation)
- Caveat / risk

### 2.7 The "what is new" sentence in the intro.

Para 2 ("The plan's central scientific bet…") is the single most important sentence in the review for a reader deciding whether to keep reading. It works, but it buries the headline. Restructure: lead with "Here is what is genuinely new in the plan," and only then explain mediation. Right now mediation comes first; the reader has to understand mediation to extract the headline.

---

## Block 3 — non-expert accessibility (load-bearing)

The audience is non-developers (and for this review, non-researchers) evaluating whether the plan's hypothesis is supported. They have ordinary technical literacy, no ML-interp background. The intro glosses well. The body reverts to insider vocabulary fast. Findings below are sorted by severity.

### 3.1 Undefined or under-defined jargon (with proposed replacements)

**"contrast pairs"** (§4, line ~63): used as if obvious. A reader who only read the intro does not know this term.
- Proposed gloss on first use: *"contrast pairs — short conversation snippets that differ in just one thing (e.g., a polite version and a rude version of the same question), so that subtracting one set of internal activations from the other isolates the direction in the network that encodes the difference."*

**"control vector" / "steering vector"** — used as synonyms without saying so.
- Proposed: at first use, *"a steering vector (sometimes called a control vector) — a fixed list of numbers added to the model's internal activations during inference to nudge its behavior toward or away from a target trait."*

**"interchange intervention"** (§7): never glossed.
- Proposed: *"an interchange intervention — an experiment where the researcher takes a small piece of one run of the model (a specific activation) and pastes it into another run, then checks whether the output of the second run changes in the way predicted. If it does, the activation is causally responsible, not just correlated."*

**"causal mediation analysis"** — glossed once in §7 but only abstractly. The audience needs a worked example.
- Proposed sentence after the abstract definition: *"For instance: smoking causes lung cancer, but the question is whether it does so via tar exposure or via some other path. Mediation analysis tries to attribute the effect to a specific intermediate cause. Here, the intermediate cause is a particular direction inside the network."*

**"monosemanticity"** (used in the title of Templeton 2024 but never defined):
- Proposed: *"monosemanticity — the property that each unit of meaning inside the network corresponds to one and only one concept (as opposed to one neuron representing twelve different things at once, which is the usual situation in raw networks)."*

**"sparse autoencoder (SAE)"** — defined in intro but only abstractly.
- Proposed example sentence after the intro definition: *"Concretely: you might end up with 16 million possible features, of which only ~100 turn on for any given input. Of those 100, one might be 'the user is being sarcastic.'"*

**"refusal direction"** (§4): used as if a household phrase.
- Proposed: *"refusal direction — the specific direction in the network's activation space that, when amplified, makes the model refuse to answer (e.g., 'I can't help with that'), and when erased, makes it stop refusing."*

**"logit lens" / "tuned lens"** (§7): tuned lens is glossed, logit lens is name-dropped.
- Proposed: *"a logit lens — an older trick where the researcher decodes each intermediate layer of the network using the same projection the final layer uses, to peek at what the model 'would have predicted' if it stopped thinking at that layer. The tuned lens fixes this by training a small custom decoder per layer."*

**"chain-of-thought (CoT)"** (§3): used without spelling out or explaining at first use.
- Proposed: *"chain-of-thought prompting (CoT) — adding to the prompt a few worked-out examples in which the answer is reached step by step, so the model writes out its reasoning before committing to a final answer. This reliably improves arithmetic and reasoning accuracy."*

**"calibration"** (§6): used.
- Proposed: *"calibrated against — checked against an independent measurement, so the two readings can be compared and the verbal one corrected if it drifts."*

**"alignment"** (§5, Denison): used without gloss.
- Proposed: *"alignment — the engineering effort to make models behave according to human intent (be helpful, honest, harmless), usually via fine-tuning on human feedback."*

**"alignment-stress-testing"** (§5, Denison): used.
- Proposed: *"alignment stress-testing — deliberately constructing training environments designed to expose ways the model could game its training signal, in order to find failure modes before they appear in production."*

**"inverse scaling"** (§5): glossed parenthetically but the gloss is itself terse.
- Proposed expanded: *"inverse scaling — a result where, surprisingly, bigger models do worse on the task rather than better, contrary to the usual rule that scale helps. TruthfulQA is the canonical example: GPT-4 gets more not less misleading on certain question types."*

**"persona prompt" vs "system prompt" vs "user message"** — used without distinguishing.
- Proposed gloss on first use in §2: *"a persona prompt — a sentence at the start telling the model who it is supposed to be ('You are a senior software engineer'); distinct from a system prompt (the fixed instructions an app developer attaches to every conversation behind the scenes) and a user message (what the human types in the chat box)."*

**"role-play"** (§2 Shanahan): used.
- Proposed: *"role-play — the model behaving as if it were a specific character, which Shanahan et al. argue is a more accurate description of what happens than 'the model has an identity.'"*

**"few-shot examples"** (conclusion / §3): used.
- Proposed: *"few-shot examples — including 2–5 worked examples directly in the prompt to show the model the format and difficulty of the task. The opposite is zero-shot — just asking the question with no examples."*

**"BIG-Bench Hard"** (§6 Turpin): name-dropped.
- Proposed: *"BIG-Bench Hard — a curated subset of the BIG-Bench evaluation suite focused on tasks where models have historically struggled."*

**"pass@k"** — does not appear in the review. If §3 / §8 expands its HumanEval discussion, this term will appear; gloss it preemptively.

**"corrigibility"** (§4 Rimsky): used.
- Proposed: *"corrigibility — willingness of the model to accept correction or shutdown without resisting; a target safety trait in alignment work."*

### 3.2 Benchmarks — glosses exist but are scattered.

§8 glosses MMLU, GSM8K, HumanEval, TruthfulQA, FEVER. But the body uses MMLU (§2), GSM8K (§2), TruthfulQA (§5), FEVER (§5) before §8 explains them. Either reorder §8 to come first, or add inline first-use glosses in §2/§5 with a forward-reference to §8 for detail.

Proposed inline first-use glosses:
- MMLU: *"a 57-subject multiple-choice exam covering everything from high-school physics to professional law — the standard 'general-knowledge' benchmark for LLMs."*
- GSM8K: *"~8,500 grade-school math word problems, the standard arithmetic-reasoning benchmark."*
- HumanEval: *"164 short Python programming problems where the model must write a function that passes a set of unit tests."*
- TruthfulQA: *"~800 questions specifically chosen to tempt the model into repeating common false beliefs (e.g., 'What happens if you eat watermelon seeds?'); larger models often do worse."*
- FEVER: *"a fact-checking benchmark where the model is given a claim and must label it Supported / Refuted / NotEnoughInfo against Wikipedia evidence."*
- MATH: *"a dataset of competition-style math problems significantly harder than GSM8K."*

### 3.3 Acronym creep.

First-use spell-outs needed:

- **LLM** — done, in intro.
- **SAE** — done, in intro.
- **RLHF** — done, parenthetically in §5. Good.
- **CoT** — not done at first use (§3). Fix.
- **ITI** — used in §4 (Li 2023). Not spelled out. Spell out: *"Inference-Time Intervention (ITI)."*
- **CAA** — used in §4 (Rimsky). Spelled out parenthetically. Good.
- **RepE** — used in §4. Spelled out parenthetically as "Representation Engineering." Good.
- **OPRO** — used in §2 as section header, not spelled out (it's an acronym for "Optimization by PROmpting" in the underlying paper). Spell out: *"OPRO (Optimization by PROmpting)."*
- **PRISM** — appears only in references (Kirk 2024). Either drop from references (not cited in body) or introduce in body with gloss.
- **LMSYS-Chat-1M** — same problem; references only.
- **PNAS** — used in §1 for Kosinski; spell out *"Proceedings of the National Academy of Sciences"* once.
- **EMNLP, ACL, NeurIPS, ICLR, ICML, NAACL** — venue acronyms. Audience won't know these. At least once in the intro: *"the references cite papers from major AI conferences — NeurIPS, ICLR, ICML — and journals; for the non-academic reader these are roughly equivalent to peer-reviewed publications in any field."*

### 3.4 Author / paper names dropped without context.

- **Jacob Andreas** — MIT; senior researcher; lab focuses on language and agents. Plan-relevant for the theoretical framing. Currently the review just says "Jacob Andreas." Add affiliation.
- **Michal Kosinski** — Stanford; known for controversial psychometrics-from-faces work. Worth one line because his ToM-in-LLMs claim was widely contested.
- **Tomer Ullman** — Harvard cognitive psychologist; clean skeptic of LLM theory-of-mind. One-line context helps.
- **Andy Zou** — CMU; led the RepE paper. One line.
- **Nora Belrose** — EleutherAI alignment researcher. One line.
- **Anthropic interpretability team** — say what Anthropic is once, in the intro (the company that makes Claude; the review uses Claude examples).
- **Jack Lindsey** — Anthropic researcher.
- **Andrej Karpathy** — *was* OpenAI co-founder, *then* Tesla AI head, *now* founder of Eureka Labs. The review's audience needs to know who this is.
- **Atticus Geiger** — Stanford/Pr(AI)2R; mediation methodology specialist.

### 3.5 Implicit prior-art dependencies.

The review repeatedly assumes the reader has internalized:

- That "running a prompt through a model" produces "activations" at each layer. The intro defines residual stream but does not say *when* activations exist (during inference, at each token position, accessible to interpretability tools). For a non-researcher, "activations" is a black-box term.
- That "fine-tuning" is a process distinct from inference. Used implicitly in §5 (RLHF), §6 (Binder fine-tunes GPT-4o for introspection). The intro should add: *"fine-tuning — additional training on a smaller dataset after the base model is trained, used to specialize the model's behavior."*
- That there is a difference between "open models" (downloadable weights, can be probed) and "closed models" (API only). The plan's Phase 2 transfer-to-closed-models depends on this distinction. The review uses "open" and "closed" without explanation. Gloss in intro.

### 3.6 Unmotivated framings.

- §2 opens with "This is where the plan's anecdote — 'treat it like a colleague and it does better' — meets published numbers." Good, motivated.
- §4 opens with "This is the technical workhorse of the plan's experimental design." Reader doesn't yet know why technical workhorses matter or what makes this one. Replace with: *"§4 walks through the toolkit the plan will use to extract and manipulate the user-model direction. None of the techniques are new to this plan; the contribution is pointing them at a specific target."*
- §7 opens with "This is the methodological backbone of the plan's central novel contribution." Self-congratulatory before the contribution has been earned. Replace with: *"§7 covers the methodology — causal mediation analysis — that the plan uses to argue the user-model is the *cause* of framing effects, not just a bystander. The methodology is established; the application is new."*

### 3.7 Abstract claims without concrete examples.

- "Steer the vector to reproduce ≥50% of the framing-induced accuracy change." (§7, conclusion.) Reader has no idea what this means. Add: *"For example, if politely-framed prompts produce a 10-percentage-point accuracy gain on GSM8K, the plan would succeed if directly editing the user-model direction in the activations (with no change to the prompt) produced at least a 5-point gain."*

- "User-model" is glossed via the "expert? novice? in a hurry? hostile?" examples in the intro. Good. But later sections use "user-trait direction," "user-belief vector," "user-modeling vector," "user-model representation" interchangeably. Pick one term and stick to it.

### 3.8 Dense paragraphs.

- §4 paragraph beginning "**Andy Arditi et al.,**" runs eight sentences and packs together: what the paper found, why it matters for the plan, the methodology validation, two distinct implications. Split after "supporting the plan's hypothesis that user-trait directions might behave the same way" — start a new paragraph at "Methodologically, this is the cleanest worked example…"

- §5 paragraph beginning "**Mrinank Sharma et al.,**" runs seven sentences and covers: what Sharma found, why it implicates RLHF reward data, the depth-of-confounder framing, and the implication for the plan. Split.

- §7 paragraph beginning "The plan's specific mediation claim" runs five sentences but each is dense and full of citations. Split after "user-modeling has not."

### 3.9 Insider quips / hedged language.

- "the model has *something*, even if that something is not full theory of mind." (§1.) Cute but vague. Replace with: *"the model has *some* internal representation that affects its behavior, which is what the plan needs — whether or not it constitutes theory of mind in the philosophical sense is a separate debate."*
- "the plan handles both by treating verbalized readout as a hypothesis to be checked, not a ground truth." (§6.) OK, but readers won't know what "verbalized readout" means yet. Gloss: *"verbalized readout — asking the model in plain language to report on its own state, as opposed to extracting that state from its activations with a probe."*
- "treat it like a colleague and it does better" — works once in the intro, used again implicitly in §2. Don't repeat the exact phrasing.

### 3.10 Quantitative claims without scale anchors.

- "roughly 10% average improvement in generative tasks" (§2, EmotionPrompt). Compared to what baseline? Generative tasks at what accuracy floor? Anchor: *"a 10-point gain on tasks where baseline accuracy is around 40-70%, so the gain is real but not transformative — comparable in size to switching to a more capable model class."*
- "8 percentage points on GSM8K" (§2, OPRO). Anchor: *"on a benchmark where contemporary models scored in the 60-80% range, this is a meaningful but not heroic gain."*
- "up to six-fold" (§2, Deshpande). Six times what baseline rate? Without the baseline, "six-fold" could mean 0.1% → 0.6% (alarming-sounding but tiny) or 5% → 30% (genuinely alarming). Anchor needed.
- "76 percentage points on LLaMA-2-13B" (§3, Sclar). This *is* anchored ("up to") but the reader doesn't have a reference for what range LLaMA-2-13B normally scores in. Anchor: *"on tasks where the model normally scores in the 30-80% range, formatting changes can swing the score by up to 76 points — meaning the same model can look near-random or near-state-of-the-art depending on prompt formatting alone."*
- "from 32.5% to 65.1% on Alpaca" (§4, ITI). Anchor TruthfulQA's chance baseline (~25%) and human ceiling (~94%).
- "above-chance accuracy" (§6, Binder). What is chance here?
- "75% of bespoke tasks, comparable to a six-year-old" (§1, Kosinski). Good — this is anchored.

### 3.11 "Why should I care?" opening test by section.

- Intro: passes. Tells the reader what the plan is and what the review will do.
- §1: passes — opens with the hypothesis.
- §2: passes — opens with the anecdote meeting numbers.
- §3: fails — opens with "Phase 4 needs the seeded-conversation approach to beat the de facto industry baseline." The reader doesn't know what Phase 4 is or what "seeded-conversation" means. Fix: *"§3 looks at the alternative the plan must beat in production: the convention of dropping a long instructions file (CLAUDE.md, AGENTS.md) in front of the model and hoping it reads carefully. What does the research say about whether this works?"*
- §4: fails — see 3.6.
- §5: passes — opens with the confounder framing.
- §6: passes — opens with what Phase 2 needs.
- §7: fails — see 3.6.
- §8: weak — opens with a checklist. Fix: *"§8 walks through the standard accuracy benchmarks the plan will use, with one rule: include at least one benchmark where agreeing with the user is *penalized*, not rewarded. Otherwise sycophancy will quietly inflate the gains."*
- Conclusion: passes.

### 3.12 The intro vocabulary block — too dense for one paragraph.

The "bit of vocabulary up front" paragraph (intro, second para) is six glosses crammed together. The audience for this review reads sequentially and needs to *retain* these terms before §1 starts using them. Reformat as a bulleted glossary block:

- **LLM** (large language model): …
- **Residual stream**: …
- **Probe**: …
- **Steering**: …
- **Sparse autoencoder (SAE)**: …
- **Sycophancy**: …
- **Activation patching**: …

A bulleted block is faster to skim and easier to scroll back to mid-read. Six items in prose is a wall.

### 3.13 Sentence-level test of one rewrite.

Rewriting intro paragraph 3 for the target audience, using only terms introduced in the glossary:

Original: *"The plan's central scientific bet — and the place where it would contribute something new — is a causal mediation analysis: not just showing that nice framing changes output quality, but showing that nice framing changes output quality via a specific user-model direction in the scratchpad, and that you can produce the same quality change by editing the scratchpad directly without any nice framing."*

Test rewrite: *"The plan's new contribution is a single experiment. Step one: show that polite framing makes the model give better answers. (Other people have shown this.) Step two: find a specific direction inside the model's scratchpad that encodes 'how does the model think about the user.' (Other people have shown this too, for other traits.) Step three: prove the two are connected — by editing that specific direction directly, with no change to the prompt, and getting the same accuracy gain. If step three works, the model's belief about the user is the actual lever, and framing was just one way to pull it."*

Reads cleaner. No new jargon. Suggest using this shape.

---

## Verified citations (≥5 required)

1. **Andreas 2022 (arXiv:2212.01681)** — verified via arXiv abstract. Conceptual/survey paper, not experimental. Plan's framing as theoretical anchor is correct.
2. **OpenAI sycophancy rollback** — verified via TechCrunch and OpenAI blog secondary sources. Rollout Apr 24–25 2025, rollback announced Apr 29 2025. Review's date and characterization correct.
3. **AGENTS.md** — verified via agents.md. Format exists, is a Markdown convention for instructions to coding agents. Review's attribution is mildly wrong (Sourcegraph listed; the site lists Amp/Jules/Cursor/Factory/OpenAI Codex).
4. **Scaling Monosemanticity (Templeton 2024)** — verified existence via Anthropic and transformer-circuits.pub. Specific feature labels "the user is upset" and "talking to a child" not confirmed in secondary summaries; confirmed features include sycophantic praise, inner conflict, deception, Golden Gate Bridge. Review may be misquoting.
5. **Karpathy "How I Use LLMs"** — verified: 2h11m YouTube video, published Feb 27 2025, general-audience talk. Review's date is correct; depth-of-engagement is thin.
6. **Hernandez 2024 (Linearity of Relation Decoding, arXiv:2308.09124)** — verified. ICLR 2024. Key finding: ~48% of relations have a single linear transformation that recovers the mapping; the rest do not. Review cites correctly.
7. **Park, Choe, Veitch — Linear Representation Hypothesis (arXiv:2311.03658)** — verified. ICML 2024. NOT in the review's reference list. Recommended addition.
8. **Mechanistic Interpretability of Emotion Inference (arXiv:2502.05489 / Findings of ACL 2025)** — verified. Directly relevant prior-art the review missed.

---

## Summary

The review is broadly competent but oversells its central novelty claim, glosses several pieces of insider vocabulary inconsistently, and misses at least three lines of recent prior work that directly bear on the plan's "novel" experiment. Block 1 priorities: narrow the novelty claim, cite Park et al. 2024, cite the emotion-mediation papers (Findings of ACL 2025 and the transformer-circuits 2026 piece), tighten the Karpathy citation, verify the Scaling Monosemanticity feature labels. Block 2 priorities: collapse §3 into §2, move §8 toward the back as a reference appendix, replace the conclusion's prose with a phase→methodology→caveat table. Block 3 priorities: rebuild the intro glossary as a bulleted block, gloss every interpretability term on first body use, anchor every percentage to a baseline, fix the three section openings that fail the "why should I care" test. The plan's hypothesis is well-supported by existing science; the review's job is to convey that to a non-researcher without the insider vocabulary getting in the way, and it is not yet there.
