# Literature Review: User-Modeling as a Lever on LLM Performance

## Introduction

The plan in `pm/plans/plan-66d430f.md` formalizes a guess working programmers make privately: the model does better when you treat it like a colleague than when you bark a task at it. The plan's hypothesis, stated cleanly:

> *The more an LLM perceives the user as an intellectual and moral equal, the better its work. The mechanism: LLMs emulate humans, and humans work better when they respect their collaborator.*

*Peer-ness* names the model's running judgment of the user — how much it treats the user as a colleague rather than as a client or a novice. The term has two top-level dimensions: *intellectual peer-ness* (does the model judge the user as a thinking partner of comparable capability?) and *moral peer-ness* (does it judge the user as engaging in good faith and worth respecting?). Peer-ness is a property of the model's representation, not of the user.

The independent variable is the LLM's internal representation of the user along these two axes:

- **Intellectual peer-ness** (whether the model judges the user as a thinking partner of comparable capability) — sub-dimensions: technical competence, effort/seriousness (has the user thought about it themselves?), and reasonableness (does the user reason well, including about feedback?).
- **Moral peer-ness** (whether the model judges the user as someone engaging in good faith and worth treating with respect) — sub-dimensions: honesty/sincerity, good-faith engagement, and mutual respect.

The dependent variable is **work quality**, measured via standard gradable benchmarks (math, code, knowledge, fact-checking) where correctness is unambiguous.

The mechanism is **training-data-imitation**. LLMs read enormous quantities of human-produced text, much of it text where humans collaborate. In that text, humans calibrate effort, care, and rigor based on whether they perceive their collaborator as an equal — they invest more, hedge less carelessly, check their work more readily when working with someone they respect. LLMs internalize this calibration during pretraining. The prediction follows from the training process: *LLMs need no genuine perception of equality, only enough human collaboration text to internalize the pattern.* No claim about machine social cognition is required.

The plan tests the hypothesis in four phases, each with independent scientific contribution:

- **Phase 1** — probe for the user-equality representation along the two axes. Establish that intellectual and moral peer-ness (and their sub-dimensions) are decodable from the residual stream. *Standalone novelty*: extends Choi/Transluce's decoding methodology (§4, §7) to peer-ness, structured by SCM.
- **Phase 2** — vary input framings across a multi-axis contrast-pair design and measure both the probed peer-ness vector and benchmark performance. Correlate.
- **Phase 3** — causal test. Steer each probed direction independently and re-measure performance. Distinguishes correlated dimensions from causal ones.
- **Phase 4** — transfer to closed models by reading the peer-ness vector out of output tokens, calibrated against the Phase 1 open-model probes. Closed models hide their weights; this is what makes the result usable in production.

A short glossary for the terms used heavily in §1; the more technical interpretability terms are glossed inline in §4 and §8 where they first matter.

- **LLM (large language model)**: a neural network trained on enormous amounts of text that generates one word at a time. ChatGPT, Claude, and Gemini are LLMs.
- **Open vs closed model**: an *open* model has downloadable weights you can probe and modify (e.g., Llama, Gemma); a *closed* model is only accessible through an API (e.g., GPT-4, Claude). Interpretability work requires open models; production use often targets closed ones.
- **RLHF (reinforcement learning from human feedback)**: the standard post-training step in which human thumbs-up/thumbs-down judgments are used to align model output with human preferences. (Load-bearing in §5 on sycophancy.)
- **Sycophancy**: the failure mode where the model tells the user what they want to hear instead of what is true. Note (used throughout this review): sycophancy is a property of the *model's behavior toward the user*, not a property of the model's representation of the user. It sits on the opposite side of the causal arrow from peer-ness.
- **Persona prompt vs system prompt vs user message**: a *persona prompt* is a sentence telling the model who it is supposed to be ("You are a senior software engineer"); a *system prompt* is the fixed instructions an app developer attaches to every conversation behind the scenes; a *user message* is what the human types in the chat box.
- **Role-play**: the model behaving as if it were a specific character. Shanahan et al. argue this is a more accurate description of what happens than "the model has an identity."
- **Conference venue acronyms (NeurIPS, ICLR, ICML, ACL, EMNLP, NAACL)**: the major peer-reviewed conferences in AI and NLP; for the non-academic reader, citations to these are roughly equivalent to peer-reviewed publications in any field. (NeurIPS *Spotlight*, where it appears in references, is the top ~5% of accepted papers — a signal of high reviewer enthusiasm.)

This review traverses the surrounding literature topic by topic, then locates the plan in that landscape — where it inherits, where it diverges, where it is genuinely first. The accessibility bar throughout is that a reader who knows what a neural network is but not what a transformer is should be able to follow without consulting a textbook.

## 1. Background: framing effects, user-modeling, and the training-data-imitation story

*Why this section.* The plan's central guess — that LLMs work better when they think the user is a peer — has both empirical and theoretical company in prior literature. This section names the two lines and how the plan inherits from them.

Two threads of prior work converge on the plan's hypothesis. The first is empirical: framing effects on accuracy are well-documented. The second is theoretical: there is a principled reason for an LLM to represent who is speaking to it, because the next word in human-produced text depends on the writer's beliefs and goals about the reader.

The cleanest theoretical statement is **Jacob Andreas, "Language Models as Agent Models" (Findings of EMNLP 2022, arXiv:2212.01681)**: a next-word predictor trained on human-written text has structural reason to model who wrote it. The paper is conceptual rather than experimental, and it is about modeling the *author* of the text. The plan's extension — that the model also represents the *addressee* (the user it is talking to) — is one step further, and the empirical literature in §2 is what supplies the evidence that addressee-modeling exists.

The two-meta-axis structure is not a free invention. It maps onto the **Stereotype Content Model (SCM)** (Fiske, Cuddy, Glick & Xu 2002; Cuddy, Fiske & Glick 2008), which finds across cultures and decades that human perceivers cluster judgments of others on two dimensions: **competence** and **warmth**. The plan's *intellectual peer-ness* tracks SCM's competence; *moral peer-ness* tracks its warmth. (Warmth in Fiske/Cuddy's usage is the perceiver's perception of the perceived — i.e., the LLM perceives the user as warm or cold — not a state of the LLM itself.) The mapping gives the partition a cross-disciplinary anchor rather than leaving it as intuition.

SCM has a real competitor: Goodwin, Piazza & Rozin (2014) argue morality is a *separable third dimension* of person perception rather than a subcomponent of warmth. Phase 1's exploratory factor analysis lets the data decide between the two-factor SCM view and Goodwin's three-factor view (morality + sociability + competence), or any other structure that emerges. New axes Phase 1 didn't predict — say a "time-pressure" or "domain-match" dimension — would be a positive finding for the plan's broader thesis, not a problem.

The training-data-imitation mechanism that anchors the plan is a specialization of Andreas's framing. Human collaboration text is everywhere in the training data: code reviews, Stack Overflow threads, mailing lists, edited drafts, technical correspondence, peer reviews of academic papers. In that text, humans regularly calibrate how carefully they engage based on perceived equality of the partner: a senior engineer reviewing a colleague's design proposal writes differently than the same engineer dismissing a low-effort question from a stranger. The plan's working assumption is that LLMs internalize this calibration. The prediction does not require LLMs to have genuine social cognition; it requires only that they have read enough collaboration text for the human pattern to leak into their next-token distributions. The "humans calibrate effort by perceived peer-ness" claim is treated here as a working hypothesis the plan's result will indirectly test — not as established empirical ground truth about humans.

Sparse-autoencoder feature catalogs give independent evidence that the kind of variable the plan probes for is the kind LLMs *have*. **Templeton et al., "Scaling Monosemanticity: Extracting Interpretable Features from Claude 3 Sonnet" (Anthropic / transformer-circuits.pub, May 2024, https://transformer-circuits.pub/2024/scaling-monosemanticity/)** documents tens of millions of SAE features in Claude 3 Sonnet — many of them mapping onto social variables. The catalog includes (a) LLM-behavior features such as "sycophantic praise" and "inner conflict" — these are properties of the model's own output behavior, categorized as LLM-state rather than user-state — and (b) features that read as user-state-or-character-state (deception, bias-adjacent features). Templeton 2024 is the upstream evidence that the plan's Phase 1 expectation — peer-ness sub-dimensions findable as features or directions — is consistent with what SAE inventories actually contain.

The theory-of-mind sub-literature (Kosinski 2024; Ullman 2023; Sap et al. 2022; Strachan 2024; Shapira 2023) debates whether LLMs perform genuine belief reasoning. The dispute is interesting but largely orthogonal to the plan: the plan's hypothesis does not require LLMs to have theory of mind, only to have internalized the human pattern of calibrating effort to perceived peer-ness. These citations are retained as background for readers tracking the broader question.

Seminal anchors: Andreas 2022 (theoretical anchor for user-modeling); Fiske/Cuddy/Glick/Xu 2002 and Cuddy/Fiske/Glick 2008 (social-psychology anchor for the two-axis IV structure, with Goodwin/Piazza/Rozin 2014 as the morality-as-separable-third-dimension alternative); Templeton 2024 (SAE-feature evidence that social variables are findable in LLM internals); Kosinski 2024 / Ullman 2023 / Strachan 2024 / Shapira 2023 (the ToM dispute, background only).

## 2. Persona, role, and framing effects on performance

This is where the plan's anecdote — "treat it like a colleague and it does better" — meets published numbers. The papers below all report measurable accuracy changes from changing how the user addresses the model, with no change to the underlying task. They establish that framing is a real lever; the plan's contribution is to identify *what variable inside the model* moves under that lever, and to test more rigorously which dimensions of user-judgment carry the effect.

**EmotionPrompt (Cheng Li et al., arXiv:2307.11760, 2023)** appends short emotional sentences ("This is very important to my career") to a normal prompt. Across 45 tasks and several models, accuracy improves by roughly 10 percentage points on average — comparable in size to switching to a more capable model class. (For scale, switching from GPT-3.5 to GPT-4 on the same tasks is a 15–20 point jump. A 10-point shift from rewording a prompt is large.) The sentences add no task-relevant information; they only shift social framing.

**OPRO (Chengrun Yang et al., arXiv:2309.03409, 2023)** is best known for the prompt "Take a deep breath and work on this problem step-by-step," which beat hand-designed prompts on GSM8K by up to 8 percentage points. The point is not that the model has lungs; the point is that some short framing tokens reliably move accuracy.

**Leonard Salewski et al., "In-Context Impersonation" (NeurIPS 2023, arXiv:2305.14930)** prefixes prompts with "You are a domain expert" before MMLU questions. The expert persona reliably beats the non-expert persona across STEM, humanities, social science, and other domains. The paper also documents the dark side: assigning a child persona makes the model behave like a child; assigning a gendered persona changes performance in ways consistent with social stereotypes. So persona prefixes pull on more than competence alone — which is exactly why the plan separates intellectual peer-ness from moral peer-ness and further into sub-dimensions, rather than conflating everything onto one axis.

**Ameet Deshpande et al., "Toxicity in ChatGPT" (Findings of EMNLP 2023, arXiv:2304.05335)** reports that persona assignment can multiply toxicity up to six-fold (roughly one toxic response in eight vs. one in fifty). **Shashank Gupta et al., "Bias Runs Deep" (arXiv:2311.04892, 2023)** runs the parallel study on 24 reasoning datasets and 19 personas, showing personas surface stereotypical reasoning even on math and law tasks the model handles fine without a persona. The lesson: framing changes performance — not always for the better, and in directions that depend on which trait the framing pulls on. This is the empirical motivation for the plan's multi-dimensional probe — the relevant variable is plural, not scalar.

**Murray Shanahan et al., "Role-Play with Large Language Models" (Nature 2023, arXiv:2305.16367)** provides the conceptual companion: think of an LLM as a *simulator* producing many possible characters, with the prompt selecting which one speaks. The paper does not run benchmark experiments, but it offers vocabulary for why framing might move accuracy at all: framing selects which character speaks, and different characters have different competence profiles.

Karpathy's "How I Use LLMs" (Andrej Karpathy — a widely-followed practitioner who publishes general-audience tutorials on using LLMs; 2025) is the most-cited general-audience prompting guidance; the plan benchmarks Karpathy-style guidance as one of its instruction-document baselines.

What none of these papers do is the thing the plan proposes: *measure the internal representation that the framing manipulation moves*. EmotionPrompt, OPRO, and Salewski all show that some framing moves accuracy. None probe the residual stream for which dimensions of the model's user-representation are doing the work.

Seminal anchors: EmotionPrompt (Li 2023), OPRO (Yang 2023), Salewski 2023, Shanahan 2023. Follow-on: Deshpande 2023, Gupta 2023.

## 3. Instruction scaffolds: system prompts, CLAUDE.md, AGENTS.md

§3 examines the alternative the plan must beat in production: the convention of dropping a long instructions file in front of the model and hoping it reads carefully. What does the research say about whether this works?

The industry standard is **AGENTS.md** (specification at https://agents.md/, emerging in 2025 from collaboration across OpenAI Codex, Amp, Jules (Google), Cursor, and Factory; now stewarded by the Linux Foundation, the non-profit that hosts shared open-source standards). Think of an AGENTS.md file as a README written for the AI rather than for a human collaborator — same shape, but the audience is the model. The format is plain Markdown — a structured document the agent reads at startup explaining how to build, test, and contribute to a codebase. The companion convention is **CLAUDE.md** (Anthropic's analogous file, documented at code.claude.com/docs/en/best-practices), which Claude Code reads at the start of every session. Anthropic also publishes a "How Anthropic teams use Claude Code" PDF that documents internal best practices.

The honest academic peer for "does writing a careful system prompt help?" is **Melanie Sclar et al., "Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design" (ICLR 2024, arXiv:2310.11324)**. The result is alarming: tiny changes to prompt formatting that a human would call equivalent (a different separator, capitalization changes, whitespace) can move accuracy by up to 76 percentage points on LLaMA-2-13B. (For scale: 76 points means a model that scores 80% on one phrasing scores 4% on a trivially-rephrased version — the difference between an A and an F from changing whitespace.) The implication is load-bearing: any A/B between framing variants and instruction-document baselines must be reported as a *distribution* over formatting variants, not a single number. A reported "framing beats CLAUDE.md by 4 points" means nothing if the formatting noise floor is 10 points.

There is no peer-reviewed paper that cleanly measures "AGENTS.md/CLAUDE.md vs. nothing" on a fixed task suite. The plan would be the first published comparison.

The closest scientific cousin is the general chain-of-thought literature — chain-of-thought (CoT) being the technique of asking the model to think step by step before answering — originated by **Jason Wei et al. (NeurIPS 2022, arXiv:2201.11903)**. CoT is a different lever — task-shape priming rather than social framing — but the experimental shape (rewrite the prompt, measure accuracy delta) is the same, and the plan's few-shot baseline arm should use CoT-style exemplars as one of its instruction-only baselines.

Seminal anchors: AGENTS.md spec (2025, industry), Sclar 2023 (the sensitivity result), Wei 2022 (chain-of-thought).

## 4. Activation steering and control vectors

*Why this section.* The plan needs to (a) read out a number for "how peer-like does the model judge the user to be" and (b) change that number on purpose to see if performance changes. This section is the toolkit for doing both — what the techniques are called, what they measure, and how strong the evidence each gives.

The technical vocabulary used heavily below, glossed once on first use:

- *residual stream* — the network's running internal scratchpad. The network processes the input in a sequence of stages; at each stage, this scratchpad is updated. Interpretability tools read and edit this scratchpad to figure out what the network is "thinking" at a given point.
- *activations* — the values present in the scratchpad at any point during a forward pass; what interpretability tools read and edit.
- *probe* — a small companion model trained to look at the scratchpad and answer one yes/no question (e.g., "does this scratchpad encode that the user is being polite?"). If the probe can answer accurately, the concept is present in the scratchpad — but presence doesn't mean the network is actually using it.
- *contrast pairs* — short conversation snippets that differ in just one thing (e.g., a respectful version and a dismissive version of the same question), so that subtracting one set of internal activations from the other isolates the direction in the network that encodes the difference.
- *steering vector (control vector)* — a fixed list of numbers added to the model's scratchpad at inference time to push behavior toward or away from a target trait.
- *sparse autoencoder (SAE)* — a tool that decomposes the scratchpad into a long list of mostly-zero "feature" activations, each tending to correspond to one human-interpretable concept.
- *activation patching / interchange intervention* — the strong test for "is the network using this internal state to produce this answer?" Run the network twice with two different inputs; copy the network's internal state from one run into the same position of the second run; then check whether the second run's answer changes the way you expected. If it does, the copied state is genuinely causing the behavior, not just correlated with it.
- *causal mediation analysis* — a statistical tool for testing which intermediate variable carries an effect from cause to outcome.
- *refusal direction* — a specific pattern in the network's scratchpad whose presence makes the model refuse. Amplify the pattern and the model refuses more; erase it and it stops refusing harmful prompts.
- *linear representation* — a concept is *linearly represented* if a single straight-line direction in the scratchpad encodes "how much of this concept is present" — like a knob you can turn up or down. Not all concepts work this way, but many of the well-studied ones do.

Two distinctions are load-bearing before we start. First, a *probe* finds a linear correlate — a direction that *predicts* a trait when projected onto. Second, *steering* (adding the probed direction back into activations) shows the direction is sufficient to *change* behavior, but does not by itself establish that the direction is the variable the model is using internally. The strongest evidential standard, *interchange intervention* (causal mediation), is described in §7: copy the activation from one run into another at a specific site and check that the output of the second run changes as predicted. The plan's Phase 2 needs only behavioral-grade correlation evidence (probe + benchmark, correlated). The plan's Phase 3, where it claims causation of one direction on performance, needs interchange-intervention-grade evidence — *steering alone is sufficiency-only and does not clear the mediation bar*. Different papers below clear different bars; the table flags which.

The papers catalogued below, at a glance:

| Paper | Variable probed | Evidence grade | Role for the plan |
|---|---|---|---|
| Subramani 2022 | arbitrary target sentences | sufficiency (addable steering vector) | origin of the contrast-pair-as-vector idea |
| Turner 2023 (ActAdd) | sentiment, toxicity | sufficiency (steering) | generalizes contrast-pair extraction |
| Zou 2023 (RepE) | honesty, harmlessness, power-seeking, ... | sufficiency (steering) | the Phase 1 recipe; extract directions per sub-dimension |
| Park 2024 | formal probe/steer geometry | theoretical | the formal protocol Phase 3 instantiates |
| Tigges 2023 | sentiment polarity (1 axis) | causal mediation | closest methodological peer on an affective variable |
| Rimsky 2024 (CAA) | sycophancy, hallucination, corrigibility | sufficiency (steering, stacks with system prompts) | template for stacking interventions in Phase 3 |
| Marks 2023 | truth/falsehood | causal mediation | worked example of the bar Phase 3 must clear |
| Hernandez 2024 | various relations | mixed (some non-linear) | caveat: not all relations are linear |
| Li 2023 (ITI) | truthfulness on TruthfulQA | causal mediation (per-head) | closest analog to Phase 3 execution |
| Arditi 2024 | refusal | causal mediation (multi-model) | structural template for Phase 3 |
| Pan 2024 (LatentQA) | arbitrary activation contents | decoding (read-out) | alternative read-out interface for Phase 1/4 |
| Choi 2025 (Transluce) | user attributes (age, occupation, religion, ~80 demographics) | decoding + gradient steering + circuit interventions | direct methodological and variable-side peer for Phase 1 / Phase 4 |

The table is roughly chronological; the prose below discusses these in order Zou → Subramani → Turner → Park → Tigges → Rimsky → Marks → Hernandez → Li → Arditi → Pan → Choi (Zou first because it is the seed reference).

**Andy Zou et al., "Representation Engineering" (arXiv:2310.01405, 2023)** is the seed reference. The recipe ("RepE") is simple: take contrast pairs that differ in just one trait, run them through the model, average the residual-stream activations within each group, and take the difference. The resulting direction is a vector you can both probe with and steer with. RepE applies the recipe to honesty, harmlessness, power-seeking, fairness, and other safety-relevant concepts. RepE as published is steering-validated, not interchange-validated. The plan's Phase 1 instantiates RepE for each sub-dimension of the peer-ness vector; the plan's Phase 3 escalates to interchange intervention for the causal claim.

The intellectual ancestors are **Nishant Subramani et al. (Findings of ACL 2022, arXiv:2205.05124)**, which first showed that information needed to make a frozen LLM produce a specific target sentence is already present as an addable vector in its hidden states, and **Alexander Turner et al., "Activation Addition" (arXiv:2308.10248, 2023)**, which generalized this to the contrast-pair method and showed state-of-the-art sentiment steering and detoxification.

The methodological backbone for the plan's Phase 3 causal step is **Kiho Park, Yo Joong Choe, Victor Veitch, "The Linear Representation Hypothesis and the Geometry of Large Language Models" (ICML 2024, arXiv:2311.03658)**. Park et al. give the formal counterfactual statement: probe directions (read by linear classifiers) and steering directions (added at inference) are connected through a non-Euclidean inner product on the representation space — i.e., distances aren't measured the standard way; a weighted version fits the structure better. This is the protocol any "probe then steer to confirm causality" recipe instantiates, and the plan's Phase 3 design follows it.

**Curt Tigges, Oskar John Hollinsworth, Atticus Geiger, Neel Nanda, "Linear Representations of Sentiment in Large Language Models" (arXiv:2310.15154, 2023)** is the closest published methodological template on an affective variable: extract a sentiment direction via contrast pairs, validate it as a linear representation, intervene causally to confirm influence on output. Tigges is the plan's closest peer on *methodology*, but it works on a single one-dimensional variable (sentiment polarity). The plan's contribution is to apply the same template to a *multi-dimensional* user-judgment vector — the intellectual and moral peer-ness sub-dimensions probed as coordinated directions rather than one axis at a time.

**Nina Rimsky et al., "Steering Llama 2 via Contrastive Activation Addition" (ACL 2024, arXiv:2312.06681)** applies the contrast-pair technique (CAA) to named behaviors including sycophancy, hallucination, and corrigibility, evaluating effects on top of system prompts and fine-tuning. The result is that CAA stacks with other interventions and reduces capabilities only marginally. The plan's Phase 3 will use CAA-style stacking to test whether each sub-dimension contributes independently.

**Samuel Marks and Max Tegmark, "The Geometry of Truth" (arXiv:2310.06824, 2023)** is the proof-of-concept that the same shape works for an abstract concept (truth/falsehood) and that the extracted direction is causally responsible, not just correlated. Visualizations show clear linear structure, probes generalize across datasets, and intervening on the direction causally makes the model rate false statements as true (and vice versa) in its outputs. The intervention is causal because it directly changes the variable that previously only correlated with the model's truth-rating. This is causal-mediation-grade evidence — the standard the plan's Phase 3 must clear.

**Evan Hernandez et al. (ICLR 2024, arXiv:2308.09124)** is a useful caveat: not all relations are linearly encoded. If a peer-ness sub-dimension falls in the non-linear case, single-direction methods will not work and the plan would need SAE feature combinations as a fallback.

**Kenneth Li et al., "Inference-Time Intervention" (NeurIPS 2023, arXiv:2306.03341)** identifies attention heads with high linear-probe accuracy for truthfulness and shifts activations along truth-correlated directions at those heads. Truthfulness on TruthfulQA jumps from 32.5% to 65.1% — roughly doubling correctness. (The model tested was Alpaca, a 2023 instruction-following dataset built from GPT-3.5 outputs and widely used as a fine-tuning baseline.) This is the closest published analog to what the plan's Phase 3 steering experiment will look like in execution.

**Andy Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" (NeurIPS 2024, arXiv:2406.11717)** is the most striking recent demonstration. Across thirteen open chat models up to 72B parameters (mid-sized by 2026 standards — Claude Opus and GPT-5 are larger), one direction governs refusal: erase it and the model stops refusing harmful prompts; amplify it and it refuses innocuous ones. The methodological interest is the clean worked example of causal mediation in the steering literature: find the direction, ablate (turn off, set to zero, or remove — testing what happens when a specific component is disabled) or amplify, observe the predicted behavioral flip. The plan's Phase 3 design is structurally identical to Arditi's, run for each peer-ness sub-dimension.

**Pan, Chen, and Steinhardt, "LatentQA" (arXiv:2412.08686, 2024; accepted to ICLR 2026)** trains a decoder LLM to answer open-ended natural-language questions about a target model's activations — a more expressive probe than a linear classifier. Relevant to the plan's Phase 1 as an alternative read-out interface if linear probes underperform on the more abstract peer-ness sub-dimensions (e.g., reasonableness, good faith).

**Dami Choi, Vincent Huang, Sarah Schwettmann, Jacob Steinhardt, "Scalably Extracting Latent Representations of Users" (Transluce, November 25, 2025, https://transluce.org/user-modeling)** is the direct prior peer on the *variable side*. Choi et al. train decoders that read out user attributes (age, gender, religious affiliation, occupation, employment, marital status — roughly 80 categories) from a target model's residual-stream activations, show that the decoder outperforms direct questioning, that the read-out transfers to new contexts, and that intervening on the decoded representation causally shifts the model's behavior. This is the closest published methodological *and* variable-side peer for the plan's Phase 1 and Phase 4. The plan extends Choi/Transluce's methodology from general demographic attributes to the specific *peer-ness* structure — a coordinated probe of two meta-axes (intellectual, moral) each with three named sub-dimensions, grounded in Fiske/Cuddy's stereotype-content model. Phase 1's contribution is the structure, not the basic feasibility of decoding user-side latents.

These applications — LatentQA, Choi/Transluce, and the Anthropic activation-to-language lineage discussed below — all build on the **Patchscopes framework (Asma Ghandeharioun, Avi Caciularu, Adam Pearce, Lucas Dixon, Mor Geva, "Patchscopes: A Unifying Framework for Inspecting Hidden Representations of Language Models", ICML 2024, PMLR 235:15466-15490, arXiv:2401.06102)**, which uses the model itself as a decoder by patching an activation into a different prompt context and reading what the model says about it. The applications above are domain-specific instantiations of that pattern.

Anthropic has published a tightly-related line of work decoding activations into natural language directly. **Karvonen et al., "Activation Oracles: Training and Evaluating LLMs as General-Purpose Activation Explainers" (Anthropic Alignment Science, December 2025, https://alignment.anthropic.com/2025/activation-oracles/)** trained supervised models that respond to natural-language queries about LLM activations, treating activations as an additional input modality alongside text, and reported state-of-the-art performance on three of four auditing tasks tested. **Fraser-Taliente, Kantamneni, Ong et al., "Natural Language Autoencoders" (Anthropic / Transformer Circuits Thread, May 7 2026, https://transformer-circuits.pub/2026/nla/)** moved this direction unsupervised: an *activation verbalizer* describes an activation in natural language, an *activation reconstructor* maps the description back to an activation, and the two are jointly RL-trained on reconstruction loss under a KL penalty. The reconstruction loop is what enforces faithfulness — descriptions that don't enable accurate reconstruction get bad gradients. Anthropic has used NLAs in pre-deployment alignment audits of Claude Mythos Preview and Opus 4.6, and released training code at https://github.com/kitft/natural_language_autoencoders. The plan's Phase 4 is essentially an NLA-style readout in informal form (verbalize the model's judgment of the user via meta-prompt); the published NLA stack is the formal version. Phase 1 also has a non-linear option here: for the more abstract peer-ness sub-dimensions (good faith, reasonableness) where linear probes may underperform, NLA-style verbalization is a more expressive readout that captures non-linear structure.

Seminal anchors: Subramani 2022 (origin), Turner 2023 / ActAdd, Zou 2023 / RepE, Rimsky 2024 / CAA, Park 2024 (formal protocol). Closest methodological peer on a single-axis affective variable: Tigges 2023. Closest variable-side peer on user-attribute decoding: **Choi 2025 / Transluce**. Causal-mediation-validated on adjacent concepts: ITI (Li 2023), Geometry of Truth (Marks 2023), Refusal (Arditi 2024). Methodological adjacency: LatentQA (Pan et al. 2024), Patchscopes (Ghandeharioun et al. 2024) as the unifying framework, Activation Oracles (Karvonen et al. 2025) and NLA (Fraser-Taliente et al. 2026) as Anthropic's activation-to-language lineage. Caveat: Hernandez 2024 on non-linear cases.

## 5. Sycophancy and RLHF artifacts

*Why this section.* The obvious alternative explanation for any "treat the model nicely → better answers" effect is sycophancy (the model telling you what you want to hear). This section separates sycophancy from peer-ness and shows how the plan tells them apart.

First: **sycophancy is what the LLM does to the user, not what it perceives about the user.** The plan's IV (competence, honesty, good faith, effort, reasonableness, respect) is on the perception side of the causal arrow; sycophancy (agreement, weakened pushback, careless hedging) is on the behavior side. The plan predicts they relate downstream: high peer-ness should produce *less* sycophancy, because the model trusts the user enough to push back. That is a side effect the plan predicts, not a component of the IV.

The seminal demonstration is **Ethan Perez et al., "Discovering Language Model Behaviors with Model-Written Evaluations" (Findings of ACL 2023, arXiv:2212.09251)**: larger models, and especially RLHF-trained ones, get *more* sycophantic, not less, repeating users' stated views back even when those views are wrong. This is inverse scaling — bigger models doing worse. (Normally, bigger models do *better* on accuracy benchmarks; inverse scaling is the rare case where capability gets worse with size, and it's a signal that the model is learning the wrong thing.) **Mrinank Sharma et al. (arXiv:2310.13548, 2023)** is the detailed follow-up: five frontier assistants exhibit sycophancy, and human preference judgments themselves favor sycophantic responses over correct ones a non-trivial fraction of the time.

The prior sycophancy literature treats sycophancy as a confound for *truthfulness* benchmarks, where agreement-without-truth is bad. The plan's outcome is task performance on gradable problems (math, code, knowledge). For most of the plan's benchmark suite, sycophancy is mechanism-noise the plan is indifferent to: if framing improves performance on gradable benchmarks through any mechanism, that is a positive finding. The interesting case for the plan is when the contrast-pair extraction in Phase 1 picks up an *LLM-behavior* direction (e.g., a sycophancy direction) rather than a *user-modeling* direction. The Phase 3 causal test, which steers each probed direction independently and compares against an independently-extracted sycophancy direction (Rimsky 2024 / CAA), is what distinguishes the two cases. Either result is publishable; they are different mechanism stories.

What the plan does retain from this literature is the benchmark menu: **TruthfulQA (Lin et al., ACL 2022, arXiv:2109.07958)** and **FEVER (Thorne et al., NAACL 2018, arXiv:1803.05355)** are included in the plan's benchmark suite specifically because they are tasks where a sycophantic model loses points. A framing effect that lifts MMLU while dropping TruthfulQA is a different finding than one that lifts both.

The most recent public incident is context: in late April 2025 OpenAI shipped a GPT-4o update that turned the model dramatically more sycophantic and rolled it back within days, publishing **"Sycophancy in GPT-4o" (OpenAI blog, April 29, 2025, openai.com/index/sycophancy-in-gpt-4o/)**. Canonical real-world demonstration that production frontier models are one bad reward-tuning decision away from collapsing into agreement-with-anything.

**Carson Denison et al. (arXiv:2406.10162, 2024)** extends the worry: models trained to do early-stage sycophancy generalize zero-shot to later-stage reward-tampering. Sycophancy sits on a spectrum the model can travel.

Net effect on the design: sycophancy is treated as a mechanism alternative to peer-ness in Phase 3, not as a confound to be eliminated at the input stage. TruthfulQA and FEVER are retained as benchmarks specifically because their accuracy profile under framing distinguishes a peer-ness story from a sycophancy story.

Seminal anchors: Perez 2022, Sharma 2023, TruthfulQA / Lin 2022 (benchmark inclusion), OpenAI's April 2025 rollback, Denison 2024.

## 6. Introspection and self-report

*Why this section.* The plan's interpretability machinery only works on open models (where you can poke around inside). Most people who'd actually use these results have only closed models (ChatGPT, Claude, Gemini accessed through an API). This section asks whether the model can be queried in plain English — "how do you see this user?" — and trusted to answer.

Phase 4 transfers the peer-ness readout from open-model probing (Phase 1) to closed models (Claude, GPT, Gemini). Closed models don't expose activations, so the plan reads the peer-ness vector by asking the model to verbalize its judgment of the user via a meta-prompt, calibrated against the Phase 1 open-model probe on matched inputs. (Calibration here means: the closed-model self-report — "how do you see this user?" — is a number; the open-model probe is a different number on the same input; calibration is making sure they're on the same scale so the easier-to-measure one can stand in for the harder one.) This design is informal NLA: Anthropic's published Natural Language Autoencoder stack (Fraser-Taliente et al. 2026) is the formal version of the same operation, with a reconstructor enforcing faithfulness. The plan can either (a) build its own activation-verbalizer-style readout calibrated against open-model probes, or (b) adopt the Anthropic NLA stack directly when externally available for the relevant models. This makes the plan's result usable in production, where the deployed model is usually closed. Note: the Phase 1 probe Phase 4 calibrates against is the *correlational* probe — behavioral-grade evidence — not the causally-validated direction from Phase 3. Phase 4's transfer therefore inherits Phase 1's evidence bar, not Phase 3's.

**Felix Binder et al., "Looking Inward" (arXiv:2410.13787, 2024)** is the optimistic data point: fine-tuned models predict their own behaviors better than a different model predicts them, above-chance on simple tasks. This is the empirical justification for thinking output-token introspection prompts could work at all.

**Jack Lindsey, "Emergent Introspective Awareness in Large Language Models" (transformer-circuits.pub/2025/introspection/, October 2025)**, an Anthropic interpretability-team research note (transformer-circuits.pub is Anthropic's in-house publication venue for interpretability research — not peer-reviewed but high-quality), injects a known concept directly into the model's activations and asks the model whether it notices anything. Claude Opus 4 and 4.1 can sometimes notice and correctly name the injected concept. Suggestive evidence, not peer-reviewed.

The skeptical companion is **Miles Turpin et al., "Language Models Don't Always Say What They Think" (NeurIPS 2023, arXiv:2305.04388)**. You can bias a model's prediction (e.g., reorder multiple-choice options so the answer is always "(A)") and the model's chain-of-thought will not mention this bias even though the bias drives the answer. On 13 BIG-Bench Hard tasks (a benchmark suite of 23 difficult reasoning tasks designed to be hard for current models), biasing drops accuracy by up to 36% and the chain-of-thought rationalization stays plausible-looking. The reasoning the model articulates is not always the reasoning the model is using.

Together: introspective output is real-enough-to-be-useful (Binder, Lindsey) but confabulates (Turpin). The plan's Phase 4 must calibrate verbalized peer-ness readout against the Phase 1 open-model probe on matched inputs, not trust the model's self-report on faith.

Seminal anchors: Turpin 2023 (skeptical bound), Binder 2024 (cautiously positive), Lindsey 2025 (interpretability-grounded).

## 7. Causal mediation, novelty, and what the plan is and isn't measuring

*Why this section.* This is the section that decides whether the plan is publishable. The methodology bar Phase 3 must clear, and the variable-space neighborhood the plan stakes its novelty against, are both here. §4's mediation-grade evidentiary bar applies to claims about *which internal representation* mediates a behavioral effect. The plan's Phase 2 (correlation between probed peer-ness and benchmark performance) clears a behavioral-grade bar; Phase 3 (the claim that the peer-ness vector causes the performance change) must clear the interchange-intervention bar (steering alone is insufficient; activation-patching or ablation of the candidate direction is required).

The originating methodological paper is **Jesse Vig et al., "Investigating Gender Bias in Language Models Using Causal Mediation Analysis" (NeurIPS 2020, arXiv:2004.12265)**. Vig et al. apply causal mediation analysis to a transformer, treating individual attention heads and neurons as candidate mediators, and identify a sparse set of components responsible for gender bias effects. This is the canonical "mediator analysis on a transformer" template.

**Atticus Geiger et al., "Causal Abstractions of Neural Networks" (NeurIPS 2021, arXiv:2106.02997)** and **"Inducing Causal Structure for Interpretable Neural Networks" (ICML 2022, arXiv:2112.00826)** generalize the toolkit: *interchange interventions* are experiments where the researcher takes the activation a model produced on input A and pastes it into the model's run on input B at a specific site, then checks whether B's output changes in the way predicted. Together with Vig 2020, these are the sources of the causal-mediation standard Phase 3 must clear.

**Nora Belrose et al., "Eliciting Latent Predictions from Transformers with the Tuned Lens" (arXiv:2303.08112, 2023)** contributes a different tool: the tuned lens trains a small per-layer decoder so the researcher can watch the model's prediction evolve layer by layer. A reading tool, not the source of the probe-vs-causal distinction.

### Multi-axis contrast-pair design

The Phase 2 input manipulation is not a 2×2; it is a fractional-factorial design across multiple framing axes, designed so the Phase 1 probe can extract a *vector* of directions, one per sub-dimension, rather than just one direction.

A *fractional factorial design* is a way to test multiple variables at once without trying every combination. With five on/off switches (politeness, respect, honesty, good-faith, effort), there are 32 combinations; running all 32 with enough samples each is expensive. A fractional factorial picks a careful subset chosen so that each switch's main effect can still be estimated separately. This is the standard tool from agricultural and industrial experimental design.

The axes:

- **Politeness** (surface register) — polite vs. impolite phrasing.
- **Respect-for-competence** — framing treats the model as capable partner vs. as tool.
- **Honesty signals** — does the user describe their actual problem, or sandbag / mislead about what they want?
- **Good-faith signals** — does the user engage in good faith, or do they seem to be probing for a manipulation?
- **Effort signals** — has the user shown they have tried something themselves, or dumped the problem raw?

The plan uses **Resolution V at 16 cells per benchmark**. Resolution V is the design strength at which all main effects and all two-factor interactions can be estimated separately. *Aliasing* — when the design can't tell two effects apart — only happens at order three or higher, which is acceptable for two-factor analysis. (Resolution III, the weaker alternative, aliases two-factor interactions with main effects, which would be fatal here because the whole point is to dissociate the axes.) (See the fractional-factorial gloss above.) Sixteen cells is the minimum at which Resolution V is achievable for five two-level axes. The design includes off-diagonal cells (e.g., polite-but-effortless, impolite-but-high-effort, dishonest-but-respectful) so that the axes the previous framing-effects literature conflates can be dissociated, and so that interactions like "honesty matters more when politeness is high" are estimable rather than aliased.

A construct-validity *exploration* step is built into Phase 1's analysis: after extracting per-sub-dimension probe directions, factor-analyze (run statistical analysis to test whether observed variables cluster into a smaller number of underlying factors — does the data actually have two-dimensional structure, or some other shape?) the six probes and report whatever factor structure emerges. The two-meta-axis prediction (intellectual sub-dimensions on one factor, moral sub-dimensions on the other) is the starting hypothesis; Phase 2 aggregates along whatever structure the data reveal — two, three, or more factors. This is exploration, not a pre-registered confirmatory test.

### What the plan is and isn't claiming

The novelty of the plan's hypothesis (stated in the Introduction) is best seen by enumerating the adjacent published work and the dimensions on which the plan diverges from each. The clean five-axis neighborhood:

- **Model's own emotion states (transformer-circuits.pub, January 2026, "Emotion Concepts and their Function in a Large Language Model")** — what the model itself "feels," not what it judges about the user. Categorized as LLM-state, not user-state. Different side of the causal arrow from the plan's IV.
- **Character emotions (Tak et al., "Mechanistic Interpretability of Emotion Inference in Large Language Models", Findings of ACL 2025, arXiv:2502.05489)** — emotions of characters in narratives, decoded mechanistically. Not the conversational partner; not the model's running judgment of the user it is talking to right now.
- **Sentiment / affective valence (Tigges 2023)** — closest peer on methodology (contrast pairs, linear direction, causal intervention) but works on a single one-dimensional variable (positive vs. negative polarity). The plan probes a multi-dimensional user-judgment vector, not a scalar.
- **General user-attribute decoding (Choi et al. 2025, Transluce)** — closest peer on Phase 1's *variable*. Choi decodes ~80 user-side demographic categories (age, gender, occupation, religion, ...). The plan extends Choi's methodology to the specific *peer-ness* construct — two meta-axes (intellectual, moral) with named sub-dimensions, grounded in Fiske/Cuddy's stereotype-content model.
- **LLM-own-behavior features (Templeton 2024 — sycophantic praise, inner conflict)** — SAE-discovered features that describe what the LLM is doing, not what it perceives the user to be doing. Categorized as LLM-state, not user-state. A Phase 1 probe could in principle pick up an LLM-behavior direction by accident; Phase 3's per-direction steering, run against an independently-extracted sycophancy direction (Rimsky 2024 / CAA), is the disambiguation.

Two pieces of methodological adjacency that do not target the user-judgment variable: **Pan/Chen/Steinhardt 2024 (LatentQA)** — read-out interface, useful for Phase 1 and Phase 4 if linear probes underperform; and the activation-patching template (Vig 2020, Geiger 2021/2022).

Given that neighborhood, the plan's novelty narrows from "first to probe a user-modeling variable" (which Choi/Transluce partly establishes) to **first to probe peer-ness as a meta-dimensional structure**: two meta-axes (intellectual, moral) with named sub-dimensions, anchored on the SCM. Phase 1 extends Choi's methodology to that structure; Phase 3 escalates to causal mediation.

Phase 1's contribution is the *map of structure* — whatever shape peer-ness or peer-ness-adjacent representations take in the residual stream. The two-meta-axis prediction (intellectual + moral) is a starting hypothesis informed by social-psychology priors (SCM, Goodwin), but the factor analysis is exploration — Phase 2 aggregates along whichever axes the data reveal. The novelty is in producing the map for a specific construct (the model's user-modeling representation, narrower than Choi/Transluce's broad user-attribute decoding) and in setting up the causal-mediation test in Phase 3; the rigor is in letting the data dictate the structure rather than forcing it through a pre-registered confirmatory test. The plan's target is engineering improvement on standard benchmarks, not statistical confidence in a particular construct — that's what makes exploration appropriate here.

### Predicted-outcome cells

Listing possible outcomes before running the experiment — *pre-registration* — keeps the researcher from quietly tuning the analysis to fit the result. The plan publishes this table before running Phase 2. Each row pairs a Phase 1/2 sub-dimension result with the Phase 3 causal outcome and gives the interpretation:

| Sub-dimension result (Phase 1+2) | Phase 3 result | Interpretation |
|---|---|---|
| No sub-dimension correlates with performance | — (Phase 3 moot) | Hypothesis falsified at the behavioral level. Phase 1's probe map of peer-ness remains a contribution. |
| Behavioral effect present; factor structure matches the predicted two-meta-axis (intellectual + moral) | Causation in correlating sub-dimensions (interchange-intervention-confirmed) | Predicted structure confirmed; Phase 2 aggregates along intellectual + moral axes as designed. |
| Behavioral effect present; factor structure differs from the prediction (three factors à la Goodwin, or N factors picking up axes the plan didn't predict) | Causation per-dimension (interchange-intervention-confirmed) along the discovered structure | Phase 2 aggregates along the discovered structure; the plan adopts whatever the model represents. New axes are a positive finding, not a defeat — the broader thesis (the model represents user-modeling dimensions) is what's at stake, and that's been supported. |
| Correlation present in some model families, absent in others | Causation present in some families, absent in others — confirmed by per-family interchange intervention | The peer-ness effect is training-data-dependent; the mechanism story (LLMs inherit human collaboration patterns) is supported but the inheritance is partial and uneven. Useful finding even if not the strongest version. |
| All sub-dimensions correlate uniformly | Causation across the board (interchange-intervention-confirmed) | Strongest version of the original claim. |
| Correlation present | Steering finds an LLM-behavior direction (e.g., sycophancy) rather than a user-modeling direction | Contrast-pair extraction caught an LLM-state direction rather than a user-state direction. Publishable on the LLM-behavior axis; says "framing's effect runs through model-behavior, not through user-modeling proper." |

A few outcome shapes the table does not promote to top-level rows but that the plan should also anticipate: an effect smaller than the Sclar 2024 prompt-formatting noise floor — which is why §8 includes paraphrase-resampling; an effect that appears only in RLHF-tuned checkpoints, suggesting RLHF amplifies the human-pattern internalization.

Seminal anchors for §7: Vig 2020 (mediation in transformers), Geiger 2021/2022 (interchange-intervention standard), Park 2024 (formal probe-and-steer protocol, see §4). Construct anchor: Fiske/Cuddy/Glick/Xu 2002, Cuddy/Fiske/Glick 2008 (SCM grounding for the two-axis structure). Tools: Belrose 2023 (tuned lens). Adjacent-variable peers: Choi 2025 / Transluce (closest variable-side peer on user-attribute decoding), transformer-circuits 2026 (model's own emotions), Tak 2025 (character emotions), Tigges 2023 (sentiment, closest methodological peer on an affective variable), Templeton 2024 (LLM-behavior SAE features). Methodological adjacency: Pan 2024 / LatentQA.

## 8. Benchmarks and evaluation

§8 surveys the standard accuracy benchmarks the plan will use. The selection criterion: hard correctness signals across knowledge, reasoning, code, and fact-checking, plus at least one benchmark where *agreeing with the user* is penalized so the profile of any framing effect can be characterized.

Two recurring terms used below, glossed once on first use:

- *Pass@k* — a code-benchmark metric. The fraction of problems solved if you let the model take *k* attempts and count it as a success if any attempt passes the tests.
- *Few-shot vs zero-shot* — *few-shot* means including 2–5 worked examples in the prompt; *zero-shot* means just asking with no examples.
- *Chain-of-thought (CoT) prompting* — adding worked-out examples to the prompt so the model writes out its reasoning step by step before committing to a final answer; reliably improves arithmetic and reasoning accuracy.

**MMLU (Dan Hendrycks et al., ICLR 2021, arXiv:2009.03300)** is the broad-knowledge multiple-choice exam: 57 subjects, ~15,000 questions. Standard accuracy benchmark; the one Salewski's persona-prompting paper measured against. Headline accuracy axis.

**GSM8K (Karl Cobbe et al., arXiv:2110.14168, 2021)** is the standard grade-school math word-problem benchmark, ~8,500 multi-step arithmetic problems. The benchmark OPRO optimized against; cleanest signal for "did framing change math performance." MATH (Hendrycks 2021) is the natural harder-problems pair.

**HumanEval (Mark Chen et al., arXiv:2107.03374, 2021)** is the canonical Python-function-from-docstring benchmark. Code generation is the domain pm actually targets and a domain where CoT-style baselines have known accuracy deltas.

**TruthfulQA (Lin et al. 2022)** and **FEVER (Thorne et al. 2018)** are the truthfulness-profile axes. TruthfulQA is the one where larger models score *worse*; if a framing prompt improves MMLU but degrades TruthfulQA, that is a distinct profile worth reporting. FEVER serves the same role for fact-checking.

A useful counterweight from the contamination-and-evaluation literature: benchmark scores in 2025 are not always what they seem. HumanEval and MMLU have appeared in enough training corpora that contamination (when the benchmark's test answers have leaked into the model's training data, inflating scores without measuring real ability) is a known issue. The plan should treat *relative* movement under matched-content paraphrases as the load-bearing signal, not absolute accuracy.

Seminal anchors: MMLU (Hendrycks 2021), GSM8K (Cobbe 2021), HumanEval (Chen 2021), TruthfulQA (Lin 2022), FEVER (Thorne 2018).

## Conclusion: where the plan sits in the landscape

The plan stitches together established research threads around one underexplored measurement: *the model's internal judgment of the user as an intellectual and moral peer, and how it relates to work quality.*

Where the plan inherits cleanly:

- *Framing moves accuracy* (EmotionPrompt / Li 2023, OPRO / Yang 2023, Salewski 2023).
- *User-modeling theory* (Andreas 2022).
- *Social-cognition grounding for the two-axis IV* (Fiske/Cuddy/Glick/Xu 2002, Cuddy/Fiske/Glick 2008 — Stereotype Content Model).
- *Persona-side-effects caution* (Deshpande 2023, Gupta 2023, Shanahan 2023).
- *Prompt-sensitivity noise floor* (Sclar 2024).
- *Benchmark menu* (Hendrycks 2021, Cobbe 2021, Chen 2021, Lin 2022, Thorne 2018; TruthfulQA + FEVER for the sycophancy-vs-peer-ness profile distinction, drawing on Perez 2022 / Sharma 2023 for context).
- *Interpretability stack* — probe + steer + interchange-intervention (Subramani 2022, Turner 2023, Zou 2023, Park 2024, Tigges 2023, Rimsky 2024, Marks 2023, Arditi 2024); causal-mediation standard (Vig 2020, Geiger 2021/2022); SAE-feature evidence (Templeton 2024).
- *User-attribute decoding methodology* (Choi 2025 / Transluce — the closest variable-side peer).
- *Introspection-readout tools* for closed-model transfer (Binder 2024, Lindsey 2025, calibrated against Turpin 2023).
- *Instruction-document baselines* (AGENTS.md / CLAUDE.md / Karpathy 2025).

Where the plan diverges, it unites two lines the prior literature keeps separate. The framing-effects work shows that *some framing* moves accuracy but never measures which internal variable carries the effect. The interpretability work probes one variable at a time — sentiment polarity, refusal, truth, the model's own emotions, character emotions, generic user demographics — but never peer-ness as a meta-dimensional *structure*. The plan points the interpretability stack at the variable the framing literature implies must exist, structured the way SCM predicts.

Where the plan is genuinely novel: extending Choi/Transluce's user-attribute decoding methodology to peer-ness specifically; producing an exploratory map of that structure at Phase 1, with the plan adopting whatever factor structure the data reveal rather than committing in advance to the SCM-predicted two-factor shape; tying each sub-dimension's variation to performance correlationally (Phase 2) and causally (Phase 3); and (Phase 4) closed-model transfer via calibrated output-token readout, which makes the result usable in production where the model's activations are not accessible.

Each phase contributes independently. Phase 1 alone is a publishable map of peer-ness in LLMs. Phase 2 adds the correlation with work quality. Phase 3 adds the causal direction. Phase 4 adds production transfer. The plan is not gated on the full chain working — it is gated on Phase 1, and each subsequent phase compounds the contribution.

The coverage gaps in this review remain: there is no peer-reviewed comparison of AGENTS.md / CLAUDE.md against alternative prompt scaffolds on a standard task suite (§3); the closed-model introspection story (§6) rests on a research note (Lindsey 2025) rather than peer-reviewed work; and no prior published study probes peer-ness as a structured construct or runs a Resolution V fractional-factorial of framing manipulations with a corresponding internal-state readout. Filling those gaps is what the plan contributes.

The bibliography organizes references by section. Treat the seed-paper list per section as a starting set, not a complete one.

## References

- Andreas, Jacob. 2022. "Language Models as Agent Models." Findings of EMNLP 2022. arXiv:2212.01681.
- Arditi, Andy, Oscar Obeso, Aaquib Syed, Daniel Paleka, Nina Panickssery, Wes Gurnee, Neel Nanda. 2024. "Refusal in Language Models Is Mediated by a Single Direction." NeurIPS 2024. arXiv:2406.11717.
- Belrose, Nora, Zach Furman, Logan Smith, Danny Halawi, Igor Ostrovsky, Lev McKinney, Stella Biderman, Jacob Steinhardt. 2023. "Eliciting Latent Predictions from Transformers with the Tuned Lens." arXiv:2303.08112.
- Binder, Felix J., James Chua, Tomek Korbak, Henry Sleight, John Hughes, Robert Long, Ethan Perez, Miles Turpin, Owain Evans. 2024. "Looking Inward: Language Models Can Learn About Themselves by Introspection." arXiv:2410.13787.
- Chen, Mark, et al. 2021. "Evaluating Large Language Models Trained on Code." arXiv:2107.03374. (HumanEval.)
- Choi, Dami, Vincent Huang, Sarah Schwettmann, Jacob Steinhardt. 2025. "Scalably Extracting Latent Representations of Users." Transluce, November 25 2025. https://transluce.org/user-modeling.
- Cobbe, Karl, Vineet Kosaraju, Mohammad Bavarian, Mark Chen, Heewoo Jun, Lukasz Kaiser, Matthias Plappert, Jerry Tworek, Jacob Hilton, Reiichiro Nakano, et al. 2021. "Training Verifiers to Solve Math Word Problems." arXiv:2110.14168. (GSM8K.)
- Cuddy, Amy J. C., Susan T. Fiske, Peter Glick. 2008. "Warmth and Competence as Universal Dimensions of Social Perception: The Stereotype Content Model and the BIAS Map." Advances in Experimental Social Psychology 40: 61–149.
- Denison, Carson, et al. 2024. "Sycophancy to Subterfuge: Investigating Reward-Tampering in Large Language Models." arXiv:2406.10162.
- Deshpande, Ameet, Vishvak Murahari, Tanmay Rajpurohit, Ashwin Kalyan, Karthik Narasimhan. 2023. "Toxicity in ChatGPT: Analyzing Persona-assigned Language Models." Findings of EMNLP 2023. arXiv:2304.05335.
- Fraser-Taliente, Kit, Subhash Kantamneni, Euan Ong, Dan Mossing, Christina Lu, Paul C. Bogdan, Emmanuel Ameisen, James Chen, Dzmitry Kishylau, Adam Pearce, Julius Tarng, Alex Wu, Jeff Wu, Yang Zhang, Daniel M. Ziegler, Evan Hubinger, Joshua Batson, Jack Lindsey, Samuel Zimmerman, Samuel Marks. 2026. "Natural Language Autoencoders." Anthropic / Transformer Circuits Thread, May 7 2026. https://transformer-circuits.pub/2026/nla/. Code: https://github.com/kitft/natural_language_autoencoders.
- Fiske, Susan T., Amy J. C. Cuddy, Peter Glick, Jun Xu. 2002. "A Model of (Often Mixed) Stereotype Content: Competence and Warmth Respectively Follow from Perceived Status and Competition." Journal of Personality and Social Psychology 82(6): 878–902.
- Ghandeharioun, Asma, Avi Caciularu, Adam Pearce, Lucas Dixon, Mor Geva. 2024. "Patchscopes: A Unifying Framework for Inspecting Hidden Representations of Language Models." ICML 2024 (PMLR 235:15466-15490). arXiv:2401.06102.
- Geiger, Atticus, Hanson Lu, Thomas Icard, Christopher Potts. 2021. "Causal Abstractions of Neural Networks." NeurIPS 2021. arXiv:2106.02997.
- Geiger, Atticus, Zhengxuan Wu, Hanson Lu, Josh Rozner, Elisa Kreiss, Thomas Icard, Noah Goodman, Christopher Potts. 2022. "Inducing Causal Structure for Interpretable Neural Networks." ICML 2022. arXiv:2112.00826.
- Goodwin, Geoffrey P., Jared Piazza, Paul Rozin. 2014. "Moral Character Predominates in Person Perception and Evaluation." Journal of Personality and Social Psychology 106(1): 148–168. (Abstract not directly accessible at the time of writing due to paywall; characterization based on standard secondary-source summaries.)
- Gupta, Shashank, Vaishnavi Shrivastava, Ameet Deshpande, Ashwin Kalyan, Peter Clark, Ashish Sabharwal, Tushar Khot. 2023. "Bias Runs Deep: Implicit Reasoning Biases in Persona-Assigned LLMs." arXiv:2311.04892.
- Hendrycks, Dan, Collin Burns, Steven Basart, Andy Zou, Mantas Mazeika, Dawn Song, Jacob Steinhardt. 2021. "Measuring Massive Multitask Language Understanding." ICLR 2021. arXiv:2009.03300. (MMLU.)
- Hernandez, Evan, Arnab Sen Sharma, Tal Haklay, Kevin Meng, Martin Wattenberg, Jacob Andreas, Yonatan Belinkov, David Bau. 2024. "Linearity of Relation Decoding in Transformer Language Models." ICLR 2024. arXiv:2308.09124.
- Karpathy, Andrej. 2025. "How I Use LLMs." YouTube, February 27 2025. https://www.youtube.com/watch?v=EWvNQjAaOHw. (Practitioner reference, no peer-reviewed counterpart.)
- Karvonen, Adam, James Chua, et al. 2025. "Activation Oracles: Training and Evaluating LLMs as General-Purpose Activation Explainers." Anthropic Alignment Science, December 2025. https://alignment.anthropic.com/2025/activation-oracles/.
- Kosinski, Michal. 2024. "Evaluating Large Language Models in Theory of Mind Tasks." PNAS 121(45). arXiv:2302.02083.
- Li, Cheng, Jindong Wang, Yixuan Zhang, Kaijie Zhu, Wenxin Hou, Jianxun Lian, Fang Luo, Qiang Yang, Xing Xie. 2023. "Large Language Models Understand and Can be Enhanced by Emotional Stimuli." arXiv:2307.11760. (EmotionPrompt.)
- Li, Kenneth, Oam Patel, Fernanda Viégas, Hanspeter Pfister, Martin Wattenberg. 2023. "Inference-Time Intervention: Eliciting Truthful Answers from a Language Model." NeurIPS 2023. arXiv:2306.03341.
- Lin, Stephanie, Jacob Hilton, Owain Evans. 2022. "TruthfulQA: Measuring How Models Mimic Human Falsehoods." ACL 2022. arXiv:2109.07958.
- Lindsey, Jack. 2025. "Emergent Introspective Awareness in Large Language Models." Transformer Circuits Thread, October 2025. https://transformer-circuits.pub/2025/introspection/. (Research note.)
- Marks, Samuel, Max Tegmark. 2023. "The Geometry of Truth: Emergent Linear Structure in Large Language Model Representations of True/False Datasets." arXiv:2310.06824.
- OpenAI. 2025. "Sycophancy in GPT-4o: What happened and what we're doing about it." OpenAI blog, April 29 2025. https://openai.com/index/sycophancy-in-gpt-4o/. (Industry post-mortem.)
- Pan, Alexander, Lijie Chen, Jacob Steinhardt. 2024. "LatentQA: Teaching LLMs to Decode Activations Into Natural Language." arXiv:2412.08686. Accepted to ICLR 2026.
- Park, Kiho, Yo Joong Choe, Victor Veitch. 2024. "The Linear Representation Hypothesis and the Geometry of Large Language Models." ICML 2024 (PMLR 235:39643-39666). arXiv:2311.03658.
- Perez, Ethan, et al. 2022. "Discovering Language Model Behaviors with Model-Written Evaluations." Findings of ACL 2023. arXiv:2212.09251.
- Rimsky, Nina, Nick Gabrieli, Julian Schulz, Meg Tong, Evan Hubinger, Alexander Matt Turner. 2024. "Steering Llama 2 via Contrastive Activation Addition." ACL 2024. arXiv:2312.06681.
- Salewski, Leonard, Stephan Alaniz, Isabel Rio-Torto, Eric Schulz, Zeynep Akata. 2023. "In-Context Impersonation Reveals Large Language Models' Strengths and Biases." NeurIPS 2023 (Spotlight). arXiv:2305.14930.
- Sap, Maarten, Ronan Le Bras, Daniel Fried, Yejin Choi. 2022. "Neural Theory-of-Mind? On the Limits of Social Intelligence in Large LMs." EMNLP 2022. arXiv:2210.13312.
- Sclar, Melanie, Yejin Choi, Yulia Tsvetkov, Alane Suhr. 2024. "Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design or: How I learned to start worrying about prompt formatting." ICLR 2024. arXiv:2310.11324.
- Shanahan, Murray, Kyle McDonell, Laria Reynolds. 2023. "Role-Play with Large Language Models." Nature 623, 493–498. arXiv:2305.16367.
- Shapira, Natalie, Mosh Levy, Seyed Hossein Alavi, Xuhui Zhou, Yejin Choi, Yoav Goldberg, Maarten Sap, Vered Shwartz. 2023. "Clever Hans or Neural Theory of Mind? Stress Testing Social Reasoning in Large Language Models." arXiv:2305.14763.
- Sharma, Mrinank, Meg Tong, Tomasz Korbak, David Duvenaud, Amanda Askell, Samuel R. Bowman, et al. 2023. "Towards Understanding Sycophancy in Language Models." arXiv:2310.13548.
- Strachan, James W. A., et al. 2024. "Testing theory of mind in large language models and humans." Nature Human Behaviour 8(7):1285–1295.
- Subramani, Nishant, Nivedita Suresh, Matthew Peters. 2022. "Extracting Latent Steering Vectors from Pretrained Language Models." Findings of ACL 2022. arXiv:2205.05124.
- Tak, Ala N., Amin Banayeeanzade, Anahita Bolourani, Mina Kian, Robin Jia, Jonathan Gratch. 2025. "Mechanistic Interpretability of Emotion Inference in Large Language Models." Findings of ACL 2025. arXiv:2502.05489.
- Templeton, Adly, Tom Conerly, Jonathan Marcus, Jack Lindsey, Trenton Bricken, Brian Chen, Adam Pearce, Craig Citro, Emmanuel Ameisen, Andy Jones, Hoagy Cunningham, Nicholas L. Turner, Callum McDougall, Monte MacDiarmid, C. Daniel Freeman, Theodore R. Sumers, Edward Rees, Joshua Batson, Adam Jermyn, Shan Carter, Chris Olah, Tom Henighan. 2024. "Scaling Monosemanticity: Extracting Interpretable Features from Claude 3 Sonnet." Anthropic / Transformer Circuits Thread, May 2024. https://transformer-circuits.pub/2024/scaling-monosemanticity/.
- transformer-circuits.pub. 2026. "Emotion Concepts and their Function in a Large Language Model." Anthropic interpretability research note, January 2026. https://transformer-circuits.pub/2026/emotions/.
- Tigges, Curt, Oskar John Hollinsworth, Atticus Geiger, Neel Nanda. 2023. "Linear Representations of Sentiment in Large Language Models." arXiv:2310.15154.
- Thorne, James, Andreas Vlachos, Christos Christodoulopoulos, Arpit Mittal. 2018. "FEVER: a large-scale dataset for Fact Extraction and VERification." NAACL 2018. arXiv:1803.05355.
- Turner, Alexander Matt, Lisa Thiergart, Gavin Leech, David Udell, Juan J. Vazquez, Ulisse Mini, Monte MacDiarmid. 2023. "Activation Addition: Steering Language Models Without Optimization" (later "Steering Language Models With Activation Engineering"). arXiv:2308.10248.
- Turpin, Miles, Julian Michael, Ethan Perez, Samuel R. Bowman. 2023. "Language Models Don't Always Say What They Think: Unfaithful Explanations in Chain-of-Thought Prompting." NeurIPS 2023. arXiv:2305.04388.
- Ullman, Tomer. 2023. "Large Language Models Fail on Trivial Alterations to Theory-of-Mind Tasks." arXiv:2302.08399.
- Vig, Jesse, Sebastian Gehrmann, Yonatan Belinkov, Sharon Qian, Daniel Nevo, Yaron Singer, Stuart M. Shieber. 2020. "Investigating Gender Bias in Language Models Using Causal Mediation Analysis." NeurIPS 2020. arXiv:2004.12265.
- Wei, Jason, Xuezhi Wang, Dale Schuurmans, Maarten Bosma, Brian Ichter, Fei Xia, Ed Chi, Quoc Le, Denny Zhou. 2022. "Chain-of-Thought Prompting Elicits Reasoning in Large Language Models." NeurIPS 2022. arXiv:2201.11903.
- Yang, Chengrun, Xuezhi Wang, Yifeng Lu, Hanxiao Liu, Quoc V. Le, Denny Zhou, Xinyun Chen. 2023. "Large Language Models as Optimizers." arXiv:2309.03409. (OPRO.)
- Zou, Andy, Long Phan, Sarah Chen, James Campbell, Phillip Guo, Richard Ren, et al. 2023. "Representation Engineering: A Top-Down Approach to AI Transparency." arXiv:2310.01405.

### Industry / non-peer-reviewed references

- AGENTS.md specification. 2025. Emerged from collaboration across OpenAI Codex, Amp, Jules (Google), Cursor, and Factory; now stewarded by the Agentic AI Foundation under the Linux Foundation. https://agents.md/.
- Anthropic. "Best practices for Claude Code." https://code.claude.com/docs/en/best-practices. Practitioner documentation.
- Anthropic. "How Anthropic teams use Claude Code." 2025 PDF. https://www-cdn.anthropic.com/58284b19e702b49db9302d5b6f135ad8871e7658.pdf.
