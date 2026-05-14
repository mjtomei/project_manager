# Literature Review: User-Modeling as a Lever on LLM Performance

## Introduction

The plan in `pm/plans/plan-66d430f.md` rests on a guess that almost every working programmer who uses an LLM has made privately at some point: the model seems to do better when you treat it like a colleague than when you bark a task at it. The plan's hypothesis, stated cleanly:

> *The more an LLM perceives the user as an intellectual and moral equal, the higher the quality of the LLM's work. The cause is that LLMs emulate humans, and humans work better when they perceive their collaborator as an equal.*

The independent variable is the LLM's internal representation of the user along two meta-dimensions:

- **Intellectual peer-ness** — does the model perceive the user as a thinking-partner of comparable capability? Sub-dimensions: technical competence, effort/seriousness (has the user thought about it themselves?), and reasonableness (does the user reason well, including about feedback?).
- **Moral peer-ness** — does the model perceive the user as a trustworthy, in-good-faith collaborator? Sub-dimensions: honesty/sincerity, good-faith engagement, and mutual respect.

The dependent variable is **work quality**, measured via standard gradable benchmarks (math, code, knowledge, fact-checking) where correctness is unambiguous.

The mechanism is **training-data-imitation**. LLMs read enormous quantities of human-produced text, much of it text where humans collaborate. In that text, humans calibrate effort, care, and rigor based on whether they perceive their collaborator as an equal — they invest more, hedge less carelessly, check their work more readily when working with someone they respect. LLMs internalize this calibration during pretraining. The plan's prediction follows directly from the training process: *LLMs do not need to have genuine perception of equality; they need only to have read enough text where humans collaborate to have internalized the pattern.* No claim about machine social cognition is required.

The plan tests the hypothesis in four phases, each with independent scientific contribution:

- **Phase 1** — probe for the model's user-equality representation along the two meta-axes. Establish that intellectual peer-ness and moral peer-ness (with their sub-dimensions) are decodable from the residual stream. Standalone novelty: no published work maps a peer-ness representation in LLMs.
- **Phase 2** — vary input framings across a multi-axis contrast-pair design and measure both the probed peer-ness vector and benchmark performance. Correlate.
- **Phase 3** — causal test. Steer each probed direction independently and re-measure performance. Distinguishes correlated dimensions from causal ones.
- **Phase 4** — transfer to closed models via output-token readout of the peer-ness vector, calibrated against the open-model probes from Phase 1. This is what makes the result useful for production systems whose weights are not accessible.

A glossary up front, because the rest of this review leans on it.

- **LLM (large language model)**: a neural network trained on enormous amounts of text that generates one word at a time. ChatGPT, Claude, and Gemini are LLMs.
- **Open vs closed model**: an *open* model has downloadable weights you can probe and modify (e.g., Llama, Gemma); a *closed* model is only accessible through an API (e.g., GPT-4, Claude). Interpretability work requires open models; production use often targets closed ones.
- **Fine-tuning**: additional training on a smaller dataset after the base model is trained, used to specialize behavior (e.g., chat fine-tuning, RLHF).
- **RLHF (reinforcement learning from human feedback)**: the standard post-training step in which human thumbs-up/thumbs-down judgments are used to align model output with human preferences.
- **Alignment**: the engineering effort to make models behave according to human intent (helpful, honest, harmless), usually via RLHF and related fine-tuning.
- **Sycophancy**: the failure mode where the model tells the user what they want to hear instead of what is true.
- **Chain-of-thought (CoT) prompting**: adding worked-out examples to the prompt so the model writes out its reasoning step by step before committing to a final answer; reliably improves arithmetic and reasoning accuracy.
- **Pass@k**: a code-benchmark metric — the fraction of problems solved if you let the model take *k* attempts and count it as a success if any attempt passes the tests.
- **Persona prompt vs system prompt vs user message**: a *persona prompt* is a sentence telling the model who it is supposed to be ("You are a senior software engineer"); a *system prompt* is the fixed instructions an app developer attaches to every conversation behind the scenes; a *user message* is what the human types in the chat box.
- **Role-play**: the model behaving as if it were a specific character. Shanahan et al. argue this is a more accurate description of what happens than "the model has an identity."
- **Few-shot vs zero-shot**: *few-shot* means including 2–5 worked examples in the prompt; *zero-shot* means just asking with no examples.
- **Residual stream**: the running internal scratchpad inside the network — a long list of numbers at each layer representing "what the model is thinking" at that point.
- **Activations**: the values present in the network at any point during a forward pass; what interpretability tools read and edit.
- **Probe**: a small classifier trained to read a specific concept out of the residual stream. Finds a *correlate*, not necessarily a cause.
- **Contrast pairs**: short conversation snippets that differ in just one thing (e.g., a respectful version and a dismissive version of the same question), so that subtracting one set of internal activations from the other isolates the direction in the network that encodes the difference.
- **Steering vector (control vector)**: a fixed list of numbers added to the model's residual stream at inference time to push behavior toward or away from a target trait.
- **Sparse autoencoder (SAE)**: a tool that decomposes the residual stream into a long list of mostly-zero "feature" activations, each tending to correspond to one human-interpretable concept.
- **Activation patching / interchange intervention**: copy an activation from run A into run B at a specific site and check whether B's output changes in the way predicted. If yes, the activation is causally responsible.
- **Causal mediation analysis**: a statistical tool for testing which intermediate variable carries an effect from cause to outcome.
- **Refusal direction**: the direction in the network's activation space that, when amplified, makes the model refuse to answer.
- **Calibration**: checking one measurement against an independent one, so the two can be compared.
- **Conference venue acronyms (NeurIPS, ICLR, ICML, ACL, EMNLP, NAACL)**: the major peer-reviewed conferences in AI and NLP; for the non-academic reader, citations to these are roughly equivalent to peer-reviewed publications in any field.

This review walks the surrounding literature one topic at a time, and at the end places the plan in that landscape: where it inherits, where it diverges, where it is genuinely first. The accessibility bar throughout is that a reader who knows what a neural network is but not what a transformer is should be able to follow without consulting a textbook.

## 1. Background: framing effects, user-modeling, and the training-data-imitation story

Two threads of prior work converge on the plan's hypothesis. The first is empirical: framing effects on accuracy are well-documented. The second is theoretical: there is a principled reason for an LLM to represent who is speaking to it, because the next word in human-produced text depends on the writer's beliefs and goals about the reader.

The cleanest theoretical statement is **Jacob Andreas, "Language Models as Agent Models" (Findings of EMNLP 2022, arXiv:2212.01681)**: a model trained to predict the next word in human-written text has a structural reason to represent who is writing it. The paper is conceptual rather than experimental, and it is about modeling the *author* of the text. The plan's extension — that the model also represents the *addressee* (the user it is talking to) — is one step further, and the empirical literature in §2 is what supplies the evidence that addressee-modeling exists.

The training-data-imitation mechanism that anchors the plan is a specialization of Andreas's framing. Human collaboration text is everywhere in the training data: code reviews, Stack Overflow threads, mailing lists, edited drafts, technical correspondence, peer reviews of academic papers. In that text, humans regularly calibrate how carefully they engage based on perceived equality of the partner: a senior engineer reviewing a colleague's design proposal writes differently than the same engineer dismissing a low-effort question from a stranger. The plan's hypothesis is that LLMs internalize this calibration. The prediction does not require LLMs to have genuine social cognition; it requires only that they have read enough collaboration text for the human pattern to leak into their next-token distributions.

The theory-of-mind sub-literature (Kosinski 2024; Ullman 2023; Sap et al. 2022; Strachan 2024; Shapira 2023) debates whether LLMs perform genuine belief reasoning. The dispute is interesting but largely orthogonal to the plan: the plan's hypothesis does not require LLMs to have theory of mind, only to have internalized the human pattern of calibrating effort to perceived peer-ness. These citations are retained as background for readers tracking the broader question.

Seminal anchors: Andreas 2022 (theoretical anchor for user-modeling); Kosinski 2024 / Ullman 2023 / Strachan 2024 / Shapira 2023 (the ToM dispute, background only).

## 2. Persona, role, and framing effects on performance

This is where the plan's anecdote — "treat it like a colleague and it does better" — meets published numbers. The papers below all report measurable accuracy changes from changing how the user addresses the model, with no change to the underlying task. They establish that framing is a real lever; the plan's contribution is to identify *what variable inside the model* moves under that lever, and to test more rigorously which dimensions of user-judgment carry the effect.

**EmotionPrompt (Cheng Li et al., arXiv:2307.11760, 2023)** appends short emotional sentences ("This is very important to my career") to a normal prompt. Across 45 tasks and several models, accuracy improves by roughly 10 percentage points on average — comparable in size to switching to a more capable model class. The sentences add no task-relevant information; they only shift social framing.

**OPRO (Chengrun Yang et al., arXiv:2309.03409, 2023)** is best known for the prompt "Take a deep breath and work on this problem step-by-step," which beat hand-designed prompts on GSM8K by up to 8 percentage points. The point is not that the model has lungs; the point is that some short framing tokens reliably move accuracy.

**Leonard Salewski et al., "In-Context Impersonation" (NeurIPS 2023, arXiv:2305.14930)** prefixes prompts with "You are a domain expert" before MMLU questions. The expert persona reliably beats the non-expert persona across STEM, humanities, social science, and other domains. The paper also documents the dark side: assigning a child persona makes the model behave like a child; assigning a gendered persona changes performance in ways consistent with social stereotypes. So persona prefixes pull on more than competence alone — which is exactly why the plan separates intellectual peer-ness from moral peer-ness and further into sub-dimensions, rather than conflating everything onto one axis.

**Ameet Deshpande et al., "Toxicity in ChatGPT" (Findings of EMNLP 2023, arXiv:2304.05335)** reports that persona assignment can multiply toxicity up to six-fold over the no-persona baseline. **Shashank Gupta et al., "Bias Runs Deep" (arXiv:2311.04892, 2023)** runs the parallel study on 24 reasoning datasets and 19 personas, showing personas surface stereotypical reasoning even on math and law tasks the model handles fine without a persona. The lesson: framing changes performance, and not always for the better, and the direction depends on which trait the framing pulls on. This is the empirical motivation for the plan's multi-dimensional probe — the relevant variable is plural, not scalar.

**Murray Shanahan et al., "Role-Play with Large Language Models" (Nature 2023, arXiv:2305.16367)** provides the conceptual companion: think of an LLM as a *simulator* producing many possible characters, with the prompt selecting which one speaks. The paper does not run benchmark experiments, but it offers vocabulary for why framing might move accuracy at all: framing selects which character speaks, and different characters have different competence profiles.

Karpathy's "How I Use LLMs" (2025) is the most-cited general-audience prompting guidance; the plan benchmarks Karpathy-style guidance as one of its instruction-document baselines.

What none of these papers do is the thing the plan proposes: *measure the internal representation that the framing manipulation moves*. EmotionPrompt, OPRO, and Salewski all show that some framing moves accuracy. None probe the residual stream for which dimensions of the model's user-representation are doing the work.

Seminal anchors: EmotionPrompt (Li 2023), OPRO (Yang 2023), Salewski 2023, Shanahan 2023. Follow-on: Deshpande 2023, Gupta 2023.

## 3. Instruction scaffolds: system prompts, CLAUDE.md, AGENTS.md

§3 looks at the alternative the plan must beat in production: the convention of dropping a long instructions file in front of the model and hoping it reads carefully. What does the research say about whether this works?

The industry standard is **AGENTS.md** (specification at https://agents.md/, emerging in 2025 from collaboration across OpenAI Codex, Amp, Jules (Google), Cursor, and Factory; now stewarded by the Agentic AI Foundation under the Linux Foundation). The format is plain Markdown — a structured document the agent reads at startup explaining how to build, test, and contribute to a codebase. The companion convention is **CLAUDE.md** (Anthropic's analogous file, documented at code.claude.com/docs/en/best-practices), which Claude Code reads at the start of every session. Anthropic also publishes a "How Anthropic teams use Claude Code" PDF that documents internal best practices.

The honest academic peer for "does writing a careful system prompt help?" is **Melanie Sclar et al., "Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design" (ICLR 2024, arXiv:2310.11324)**. The result is alarming: tiny changes to prompt formatting that a human would call equivalent (a different separator, capitalization changes, whitespace) can move accuracy by up to 76 percentage points on LLaMA-2-13B. This is load-bearing context for the plan: any A/B between framing variants and instruction-document baselines must be reported as a *distribution* over formatting variants, not a single number. A reported "framing beats CLAUDE.md by 4 points" means nothing if the formatting noise floor is 10 points.

There is no peer-reviewed paper that cleanly measures "AGENTS.md/CLAUDE.md vs. nothing" on a fixed task suite, as far as a search surfaces. The plan would be the first published comparison if it lands a real measurement.

The closest scientific cousin is the general chain-of-thought literature, originated by **Jason Wei et al. (NeurIPS 2022, arXiv:2201.11903)**. CoT is a different lever — task-shape priming rather than social framing — but the experimental shape (rewrite the prompt, measure accuracy delta) is the same, and the plan's few-shot baseline arm should use CoT-style exemplars as one of its instruction-only baselines.

Seminal anchors: AGENTS.md spec (2025, industry), Sclar 2023 (the sensitivity result), Wei 2022 (chain-of-thought).

## 4. Activation steering and control vectors

This section describes the methodological backbone the plan uses to measure its IV. The plan's Phase 1 (probing the user-judgment representation) and Phase 3 (causal steering of each probed direction) both rest on the recipes catalogued below. This is not optional follow-up; it is how the IV is measured.

Two distinctions are load-bearing before we start. First, a *probe* finds a linear correlate — a direction that *predicts* a trait when projected onto. Second, *steering* (adding the probed direction back into activations) shows the direction is sufficient to *change* behavior, but does not by itself establish that the direction is the variable the model is using internally. The strongest evidential standard, *interchange intervention* (causal mediation), is described in §7: copy the activation from one run into another at a specific site and check that the output of the second run changes as predicted. The plan's Phase 2 needs only behavioral-grade correlation evidence (probe + benchmark, correlated). The plan's Phase 3, where it claims causation of one direction on performance, needs interchange-intervention-grade evidence. Different papers below clear different bars; we flag which.

**Andy Zou et al., "Representation Engineering" (arXiv:2310.01405, 2023)** is the seed reference. The recipe ("RepE") is simple: take contrast pairs that differ in just one trait, run them through the model, average the residual-stream activations within each group, and take the difference. The resulting direction is a vector you can both probe with and steer with. RepE applies the recipe to honesty, harmlessness, power-seeking, fairness, and other safety-relevant concepts. RepE as published is steering-validated, not interchange-validated. The plan's Phase 1 instantiates RepE for each sub-dimension of the peer-ness vector; the plan's Phase 3 escalates to interchange intervention for the causal claim.

The intellectual ancestors are **Nishant Subramani et al. (Findings of ACL 2022, arXiv:2205.05124)**, which first showed that information needed to make a frozen LLM produce a specific target sentence is already present as an addable vector in its hidden states, and **Alexander Turner et al., "Activation Addition" (arXiv:2308.10248, 2023)**, which generalized this to the contrast-pair method and showed state-of-the-art sentiment steering and detoxification.

The methodological backbone for the plan's Phase 3 causal step is **Kiho Park, Yo Joong Choe, Victor Veitch, "The Linear Representation Hypothesis and the Geometry of Large Language Models" (ICML 2024, arXiv:2311.03658)**. Park et al. give the formal counterfactual statement: probe directions (read by linear classifiers) and steering directions (added at inference) are mathematically connected via a non-Euclidean inner product respecting language structure. This is the protocol any "probe then steer to confirm causality" recipe instantiates, and the plan's Phase 3 design follows it.

**Curt Tigges, Oskar John Hollinsworth, Atticus Geiger, Neel Nanda, "Linear Representations of Sentiment in Large Language Models" (arXiv:2310.15154, 2023)** is the closest published methodological template on an affective variable: extract a sentiment direction via contrast pairs, validate it as a linear representation, intervene causally to confirm influence on output. Tigges is the plan's closest peer on *methodology*, but it works on a single one-dimensional variable (sentiment polarity). The plan's contribution is to apply the same template to a *multi-dimensional* user-judgment vector — the intellectual and moral peer-ness sub-dimensions probed as coordinated directions rather than one axis at a time.

**Nina Rimsky et al., "Steering Llama 2 via Contrastive Activation Addition" (ACL 2024, arXiv:2312.06681)** applies the contrast-pair technique (CAA) to named behaviors including sycophancy, hallucination, and corrigibility, evaluating effects on top of system prompts and fine-tuning. The result is that CAA stacks with other interventions and reduces capabilities only marginally. The plan's Phase 3 will use CAA-style stacking to test whether each sub-dimension contributes independently.

**Samuel Marks and Max Tegmark, "The Geometry of Truth" (arXiv:2310.06824, 2023)** is the proof-of-concept that the same shape works for an abstract concept (truth/falsehood) and that the extracted direction is causally responsible, not just correlated. Visualizations show clear linear structure, probes generalize across datasets, and surgically intervening on the direction flips whether the model treats false statements as true. This is causal-mediation-grade evidence — the standard the plan's Phase 3 must clear.

**Evan Hernandez et al. (ICLR 2024, arXiv:2308.09124)** is a useful caveat: not all relations are linearly encoded. If a peer-ness sub-dimension falls in the non-linear case, single-direction methods will not work and the plan would need SAE feature combinations as a fallback.

**Kenneth Li et al., "Inference-Time Intervention" (NeurIPS 2023, arXiv:2306.03341)** identifies attention heads with high linear-probe accuracy for truthfulness and shifts activations along truth-correlated directions at those heads. Truthfulness on TruthfulQA jumps from 32.5% to 65.1% on Alpaca. This is the closest published analog to what the plan's Phase 3 steering experiment will look like in execution.

**Andy Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" (NeurIPS 2024, arXiv:2406.11717)** is the most striking recent demonstration: across thirteen open chat models up to 72B parameters, one refusal direction such that erasing it makes the model stop refusing harmful prompts and adding it makes it refuse innocuous ones. The methodological interest is the clean worked example of causal mediation in the steering literature: find the direction, ablate or amplify, observe the predicted behavioral flip. The plan's Phase 3 design is structurally identical to Arditi's, run for each peer-ness sub-dimension.

**Pan, Chen, and Steinhardt, "LatentQA" (arXiv:2412.08686, 2024)** trains a decoder LLM to answer open-ended natural-language questions about a target model's activations — a more expressive probe than a linear classifier. Relevant to the plan's Phase 1 as an alternative read-out interface if linear probes underperform on the more abstract peer-ness sub-dimensions (e.g., reasonableness, good faith).

Seminal anchors: Subramani 2022 (origin), Turner 2023 / ActAdd, Zou 2023 / RepE, Rimsky 2023 / CAA, Park 2024 (formal protocol). Closest methodological peer (single-axis affective variable): Tigges 2023. Causal-mediation-validated on adjacent concepts: ITI (Li 2023), Geometry of Truth (Marks 2023), Refusal (Arditi 2024). Methodological adjacency: LatentQA (Pan et al. 2024). Caveat: Hernandez 2024 on non-linear cases.

## 5. Sycophancy and RLHF artifacts

The sycophancy literature is well-developed, and it is worth situating carefully relative to the plan.

The seminal demonstration is **Ethan Perez et al., "Discovering Language Model Behaviors with Model-Written Evaluations" (Findings of ACL 2023, arXiv:2212.09251)**: larger models, and especially RLHF-trained ones, get *more* sycophantic, not less, repeating users' stated views back even when those views are wrong. This is inverse scaling — bigger models doing worse. **Mrinank Sharma et al. (arXiv:2310.13548, 2023)** is the detailed follow-up: five frontier assistants exhibit sycophancy, and human preference judgments themselves favor sycophantic responses over correct ones a non-trivial fraction of the time.

The prior sycophancy literature treats sycophancy as a confound for *truthfulness* benchmarks, where agreement-without-truth is bad. The plan's outcome is task performance on gradable problems (math, code, knowledge). For most of the plan's benchmark suite, sycophancy is mechanism-noise the plan is indifferent to: if framing improves performance on gradable benchmarks through any mechanism — peer-ness perception, sycophancy, sharper attention, anything else — that is a positive finding. The Phase 3 causal test will distinguish whether the peer-ness direction is doing the work or whether a sycophancy direction in disguise is; either result is publishable.

What the plan does retain from this literature is the benchmark menu: **TruthfulQA (Lin et al., ACL 2022, arXiv:2109.07958)** and **FEVER (Thorne et al., NAACL 2018, arXiv:1803.05355)** are included in the plan's benchmark suite specifically because they are tasks where a sycophantic model loses points. A framing effect that lifts MMLU while dropping TruthfulQA is a different finding than one that lifts both.

The most recent public incident is context: in late April 2025 OpenAI shipped a GPT-4o update that turned the model dramatically more sycophantic and rolled it back within days, publishing **"Sycophancy in GPT-4o" (OpenAI blog, April 29, 2025, openai.com/index/sycophancy-in-gpt-4o/)**. Canonical real-world demonstration that production frontier models are one bad reward-tuning decision away from collapsing into agreement-with-anything.

**Carson Denison et al. (arXiv:2406.10162, 2024)** extends the worry: models trained to do early-stage sycophancy generalize zero-shot to later-stage reward-tampering. Sycophancy sits on a spectrum the model can travel.

Seminal anchors: Perez 2022, Sharma 2023, TruthfulQA / Lin 2022 (benchmark inclusion), OpenAI's April 2025 rollback, Denison 2024.

## 6. Introspection and self-report

This section describes methodology load-bearing for the plan's Phase 4 (transfer to closed models). Open-model probes from Phase 1 measure the peer-ness vector directly from activations; closed models don't expose activations, so Phase 4 instead reads out the vector by asking the model to verbalize its judgment of the user, calibrated against the Phase 1 probe ground truth on open models. This makes the plan's result usable in production, where the deployed model is usually closed.

**Felix Binder et al., "Looking Inward" (arXiv:2410.13787, 2024)** is the optimistic data point: fine-tuned models predict their own behaviors better than a different model predicts them, above-chance on simple tasks. This is the empirical justification for thinking output-token introspection prompts could work at all.

**Jack Lindsey, "Emergent Introspective Awareness in Large Language Models" (transformer-circuits.pub/2025/introspection/, October 2025)**, an Anthropic interpretability-team research note, injects a known concept directly into the model's activations and asks the model whether it notices anything. Claude Opus 4 and 4.1 can sometimes notice and correctly name the injected concept. Suggestive evidence, not peer-reviewed.

The skeptical companion is **Miles Turpin et al., "Language Models Don't Always Say What They Think" (NeurIPS 2023, arXiv:2305.04388)**. You can bias a model's prediction (e.g., reorder multiple-choice options so the answer is always "(A)") and the model's chain-of-thought will not mention this bias even though the bias drives the answer. On 13 BIG-Bench Hard tasks, biasing drops accuracy by up to 36% and the chain-of-thought rationalization stays plausible-looking. The reasoning the model articulates is not always the reasoning the model is using.

Together: introspective output is real-enough-to-be-useful (Binder, Lindsey) but confabulates (Turpin). The plan's Phase 4 must calibrate verbalized peer-ness readout against the Phase 1 open-model probe on matched inputs, not trust the model's self-report on faith.

Seminal anchors: Turpin 2023 (skeptical bound), Binder 2024 (cautiously positive), Lindsey 2025 (interpretability-grounded).

## 7. Causal mediation, novelty, and what the plan is and isn't measuring

This section covers the causal-mediation methodology the plan's Phase 3 inherits, then situates the plan's novelty against the closest adjacent works. §4's mediation-grade evidentiary bar applies to claims about *which internal representation* mediates a behavioral effect. The plan's Phase 2 (correlation between probed peer-ness and benchmark performance) clears a behavioral-grade bar; Phase 3 (the claim that the peer-ness vector causes the performance change) must clear the interchange-intervention bar.

The originating methodological paper is **Jesse Vig et al., "Investigating Gender Bias in Language Models Using Causal Mediation Analysis" (NeurIPS 2020, arXiv:2004.12265)**. Vig et al. apply causal mediation analysis to a transformer, treating individual attention heads and neurons as candidate mediators, and identify a sparse set of components responsible for gender bias effects. This is the canonical "mediator analysis on a transformer" template.

**Atticus Geiger et al., "Causal Abstractions of Neural Networks" (NeurIPS 2021, arXiv:2106.02997)** and **"Inducing Causal Structure for Interpretable Neural Networks" (ICML 2022, arXiv:2112.00826)** generalize the toolkit: *interchange interventions* are experiments where the researcher takes the activation a model produced on input A and pastes it into the model's run on input B at a specific site, then checks whether B's output changes in the way predicted. Together with Vig 2020, these are the sources of the causal-mediation standard Phase 3 must clear.

**Nora Belrose et al., "Eliciting Latent Predictions from Transformers with the Tuned Lens" (arXiv:2303.08112, 2023)** contributes a different tool: the tuned lens trains a small per-layer decoder so the researcher can watch the model's prediction evolve layer by layer. A reading tool, not the source of the probe-vs-causal distinction.

### Multi-axis contrast-pair design

The Phase 2 input manipulation is not a 2×2; it is a fractional factorial across multiple framing axes, designed so the Phase 1 probe can extract a *vector* of directions, one per sub-dimension, rather than just one direction. The axes:

- **Politeness** (surface register) — polite vs. impolite phrasing.
- **Respect-for-competence** — framing treats the model as capable partner vs. as tool.
- **Honesty signals** — does the user describe their actual problem, or sandbag / mislead about what they want?
- **Good-faith signals** — does the user engage in good faith, or do they seem to be probing for a manipulation?
- **Effort signals** — has the user shown they have tried something themselves, or dumped the problem raw?

Not all combinations are sampled — full factorial would be prohibitive, and most of the information lives in dissociating a few off-diagonal cells. The design is a fractional factorial chosen so each axis varies independently of the others across the sampled cells, with off-diagonal cells (e.g., polite-but-effortless, impolite-but-high-effort, dishonest-but-respectful) deliberately included to dissociate the axes the previous framing-effects literature conflates.

### What the plan is and isn't claiming

The plan's hypothesis, restated for the novelty anchor:

> *The more an LLM perceives the user as an intellectual and moral equal, the higher the quality of the LLM's work. The cause is that LLMs emulate humans, and humans work better when they perceive their collaborator as an equal.*

The novelty of probing this hypothesis is best seen by enumerating the adjacent published work and the dimensions on which the plan diverges from each.

- **Model's own emotion states (transformer-circuits 2026, "Emotion Concepts and their Function in a Large Language Model")** — probes what the model itself "feels," not what it judges about the user. The plan's variable is the model's *judgment of the partner*, not the model's own emotional state.
- **Character emotions (Tak et al., Findings of ACL 2025, arXiv:2502.05489)** — emotions of characters in narratives, decoded mechanistically. Not the conversational partner; not the model's running judgment of the user it is talking to right now.
- **Sentiment / affective valence (Tigges 2023)** — closest peer on methodology (contrast pairs, linear direction, causal intervention) but works on a single one-dimensional variable (positive vs. negative polarity). The plan probes a multi-dimensional user-judgment vector, not a scalar.
- **Agent personality traits (Tan et al. 2024 — cited by Cycle 1 reviewer; verify before final inclusion)** — closer than the others on the *multi-dimensional* axis, since personality is also a vector. But it is the *agent's* personality, not the model's judgment of the user. Different variable.
- **General activation-to-language decoding (Pan/Chen/Steinhardt 2024, LatentQA)** — methodology for reading out hidden activations as natural language. Useful as a read-out interface (Phase 1, Phase 4) but does not target the user-judgment variable.
- *(no published peer found)* — factual user beliefs as a decoded variable (demographics, expertise as stated facts). A search did not surface a peer-reviewed paper that decodes factual user beliefs as a load-bearing claim. If such a peer exists, it should be cited; we have not found it.

The plan's novelty is two-pronged: (a) it is the first to probe for *peer-ness* — the model's judgment of whether the user is its equal intellectually and morally — as a variable in the residual stream, and (b) it is the first to probe across multiple coordinated user-judgment dimensions (intellectual peer-ness with sub-dimensions for competence, effort, reasonableness; moral peer-ness with sub-dimensions for honesty, good faith, mutual respect) as a *vector* rather than one variable at a time.

Phase 1 alone — establishing that peer-ness is decodable from the residual stream — is a publishable contribution to the linear-representation literature. It adds peer-ness to the linear-representation map alongside language (Park 2024), sentiment polarity (Tigges 2023), truth (Marks 2023), and refusal (Arditi 2024).

### Predicted-outcome cells

Four cells the plan should enumerate up front, so the result is interpretable regardless of which obtains:

1. **No view-competence correlation in Phase 2.** Hypothesis falsified at the resolution the benchmark suite supports. Phases 3 and 4 are moot. Phase 1's probe map of peer-ness in LLMs remains a contribution.
2. **View-competence correlation present, but Phase 3 steering finds no causation.** Interesting correlational result — peer-ness predicts performance but does not cause it. Write up as such; this would suggest a common upstream cause (e.g., prompt complexity, or both being mediated by something else).
3. **View-competence correlation present, Phase 3 steering causally confirms one or more sub-dimensions.** Strongest version of the plan's claim: the named sub-dimension(s) causally influence work quality.
4. **View-competence correlation present, but the probed direction is the sycophancy direction in disguise.** Also a publishable result, just on a different mechanism — it would say "framing's competence effect is RLHF artifact, not user-modeling proper." Phase 3's per-dimension steering, including a steering test against an independently-extracted sycophancy direction (Rimsky 2024 / CAA), is what distinguishes (3) from (4).

Seminal anchors for §7: Vig 2020 (mediation in transformers), Geiger 2021/2022 (interchange-intervention standard), Park 2024 (formal probe-and-steer protocol, see §4). Tools: Belrose 2023 (tuned lens). Adjacent-variable peers: transformer-circuits 2026 (model's own emotions), Tak 2025 (character emotions), Tigges 2023 (sentiment, closest methodological peer). Methodological adjacency: Pan 2024 / LatentQA.

## 8. Benchmarks and evaluation

§8 walks through the standard accuracy benchmarks the plan will use. The selection criterion: hard correctness signals across knowledge, reasoning, code, and fact-checking, plus at least one benchmark where *agreeing with the user* is penalized so the profile of any framing effect can be characterized.

**MMLU (Dan Hendrycks et al., ICLR 2021, arXiv:2009.03300)** is the broad-knowledge multiple-choice exam: 57 subjects, ~15,000 questions. Standard accuracy benchmark; the one Salewski's persona-prompting paper measured against. Headline accuracy axis.

**GSM8K (Karl Cobbe et al., arXiv:2110.14168, 2021)** is the standard grade-school math word-problem benchmark, ~8,500 multi-step arithmetic problems. The benchmark OPRO optimized against; cleanest signal for "did framing change math performance." MATH (Hendrycks 2021) is the natural harder-problems pair.

**HumanEval (Mark Chen et al., arXiv:2107.03374, 2021)** is the canonical Python-function-from-docstring benchmark. Code generation is the domain pm actually targets and a domain where CoT-style baselines have known accuracy deltas.

**TruthfulQA (Lin et al. 2022)** and **FEVER (Thorne et al. 2018)** are the truthfulness-profile axes. TruthfulQA is the one where larger models score *worse*; if a framing prompt improves MMLU but degrades TruthfulQA, that is a distinct profile worth reporting. FEVER serves the same role for fact-checking.

A useful counterweight from the contamination-and-evaluation literature: benchmark scores in 2025 are not always what they seem. HumanEval and MMLU have appeared in enough training corpora that contamination is a known issue. The plan should treat *relative* movement under matched-content paraphrases as the load-bearing signal, not absolute accuracy.

Seminal anchors: MMLU (Hendrycks 2021), GSM8K (Cobbe 2021), HumanEval (Chen 2021), TruthfulQA (Lin 2022), FEVER (Thorne 2018).

## Conclusion: where the plan sits in the landscape

The plan stitches together established research threads in service of one underexplored measurement: *the model's internal judgment of the user as an intellectual and moral peer, and the relationship of that judgment to work quality.*

Where the plan inherits cleanly: the empirical fact that framing moves accuracy (EmotionPrompt / Li 2023, OPRO / Yang 2023, Salewski 2023); the user-modeling theoretical anchor (Andreas 2022); the persona-side-effects caution (Deshpande 2023, Gupta 2023, Shanahan 2023); the prompt-sensitivity noise floor (Sclar 2024); the standard benchmark menu (Hendrycks 2021, Cobbe 2021, Chen 2021, Lin 2022, Thorne 2018); the sycophancy-profile benchmarks (TruthfulQA, FEVER, drawing on Perez 2022 / Sharma 2023 for context); the probe-then-steer-then-interchange interpretability stack (Subramani 2022, Turner 2023, Zou 2023, Park 2024, Tigges 2023, Rimsky 2024, Marks 2023, Arditi 2024); the causal-mediation standard (Vig 2020, Geiger 2021/2022); the introspection-readout tools for closed-model transfer (Binder 2024, Lindsey 2025, calibrated against Turpin 2023's skeptical warning); and the instruction-document baselines (AGENTS.md / CLAUDE.md / Karpathy 2025, industry).

Where the plan diverges: the prior framing-effects literature shows that *some framing* moves performance but does not measure which internal variable carries the effect. The prior interpretability literature probes one variable at a time — sentiment polarity, refusal, truth, the model's own emotions, character emotions — but no published work probes a *peer-ness vector* (intellectual peer-ness × moral peer-ness with their sub-dimensions) as a coordinated structure. The plan unites the two lines: take the interpretability stack and point it at the variable the framing-effects literature implies should exist.

Where the plan is genuinely novel: probing for peer-ness in the residual stream, as a multi-dimensional vector, and tying each dimension's variation to performance both correlationally (Phase 2) and causally (Phase 3). The closest single-axis methodological peer is Tigges 2023 on sentiment polarity; the plan's contribution beyond Tigges is the multi-dimensional vector. The closest variable-side peer for a multi-dimensional probe is the agent-personality literature (Tan et al. 2024, pending verification), but that work probes the agent's own traits, not the model's judgment of the user. Phase 4 (closed-model transfer via output-token readout) makes the result usable in production where the model's activations are not accessible — a contribution to the application side that no prior peer-reviewed work covers for this variable.

Each phase contributes independently. Phase 1 alone is a publishable map of peer-ness in LLMs. Phase 2 adds the correlation with work quality. Phase 3 adds the causal direction. Phase 4 adds production transfer. The plan is not gated on the full chain working — it is gated on Phase 1, and each subsequent phase compounds the contribution.

The coverage gaps in this review remain: there is no peer-reviewed comparison of AGENTS.md / CLAUDE.md against alternative prompt scaffolds on a standard task suite (§3); the closed-model introspection story (§6) rests on a research note (Lindsey 2025) rather than peer-reviewed work; and no prior published study probes a peer-ness vector or runs a multi-axis fractional factorial of framing manipulations with a corresponding internal-state readout. Filling those gaps is what the plan contributes.

The seed-lineage reading list — covering the prior art a reader needs to evaluate the plan — is: Andreas 2022 (user-modeling theory); EmotionPrompt / Li 2023, OPRO / Yang 2023, Salewski 2023 (framing-effects evidence); Sclar 2024 (prompt-sensitivity noise floor); Wei 2022 (chain-of-thought baseline); AGENTS.md spec and Karpathy 2025 (instruction-document baselines); MMLU / GSM8K / HumanEval / TruthfulQA / FEVER (the benchmark suite); Perez 2022 / Sharma 2023 (sycophancy context for the truthfulness-profile axes); Park 2024, Zou 2023 / RepE, Tigges 2023 (interpretability methodology — the closest methodological peer); Vig 2020, Geiger 2021/2022 (causal-mediation standard for Phase 3); Marks 2023, Arditi 2024 (causal-mediation worked examples on adjacent concepts); Binder 2024, Turpin 2023, Lindsey 2025 (introspection methodology for Phase 4).

## References

- Andreas, Jacob. 2022. "Language Models as Agent Models." Findings of EMNLP 2022. arXiv:2212.01681.
- Arditi, Andy, Oscar Obeso, Aaquib Syed, Daniel Paleka, Nina Panickssery, Wes Gurnee, Neel Nanda. 2024. "Refusal in Language Models Is Mediated by a Single Direction." NeurIPS 2024. arXiv:2406.11717.
- Belrose, Nora, Zach Furman, Logan Smith, Danny Halawi, Igor Ostrovsky, Lev McKinney, Stella Biderman, Jacob Steinhardt. 2023. "Eliciting Latent Predictions from Transformers with the Tuned Lens." arXiv:2303.08112.
- Binder, Felix J., James Chua, Tomek Korbak, Henry Sleight, John Hughes, Robert Long, Ethan Perez, Miles Turpin, Owain Evans. 2024. "Looking Inward: Language Models Can Learn About Themselves by Introspection." arXiv:2410.13787.
- Chen, Mark, et al. 2021. "Evaluating Large Language Models Trained on Code." arXiv:2107.03374. (HumanEval.)
- Cobbe, Karl, Vineet Kosaraju, Mohammad Bavarian, Mark Chen, Heewoo Jun, Lukasz Kaiser, Matthias Plappert, Jerry Tworek, Jacob Hilton, Reiichiro Nakano, et al. 2021. "Training Verifiers to Solve Math Word Problems." arXiv:2110.14168. (GSM8K.)
- Denison, Carson, et al. 2024. "Sycophancy to Subterfuge: Investigating Reward-Tampering in Large Language Models." arXiv:2406.10162.
- Deshpande, Ameet, Vishvak Murahari, Tanmay Rajpurohit, Ashwin Kalyan, Karthik Narasimhan. 2023. "Toxicity in ChatGPT: Analyzing Persona-assigned Language Models." Findings of EMNLP 2023. arXiv:2304.05335.
- Geiger, Atticus, Hanson Lu, Thomas Icard, Christopher Potts. 2021. "Causal Abstractions of Neural Networks." NeurIPS 2021. arXiv:2106.02997.
- Geiger, Atticus, Zhengxuan Wu, Hanson Lu, Josh Rozner, Elisa Kreiss, Thomas Icard, Noah Goodman, Christopher Potts. 2022. "Inducing Causal Structure for Interpretable Neural Networks." ICML 2022. arXiv:2112.00826.
- Gupta, Shashank, Vaishnavi Shrivastava, Ameet Deshpande, Ashwin Kalyan, Peter Clark, Ashish Sabharwal, Tushar Khot. 2023. "Bias Runs Deep: Implicit Reasoning Biases in Persona-Assigned LLMs." arXiv:2311.04892.
- Hendrycks, Dan, Collin Burns, Steven Basart, Andy Zou, Mantas Mazeika, Dawn Song, Jacob Steinhardt. 2021. "Measuring Massive Multitask Language Understanding." ICLR 2021. arXiv:2009.03300. (MMLU.)
- Hernandez, Evan, Arnab Sen Sharma, Tal Haklay, Kevin Meng, Martin Wattenberg, Jacob Andreas, Yonatan Belinkov, David Bau. 2024. "Linearity of Relation Decoding in Transformer Language Models." ICLR 2024. arXiv:2308.09124.
- Karpathy, Andrej. 2025. "How I Use LLMs." YouTube, February 27 2025. https://www.youtube.com/watch?v=EWvNQjAaOHw. (Practitioner reference, no peer-reviewed counterpart.)
- Kosinski, Michal. 2024. "Evaluating Large Language Models in Theory of Mind Tasks." PNAS 121(45). arXiv:2302.02083.
- Li, Cheng, Jindong Wang, Yixuan Zhang, Kaijie Zhu, Wenxin Hou, Jianxun Lian, Fang Luo, Qiang Yang, Xing Xie. 2023. "Large Language Models Understand and Can be Enhanced by Emotional Stimuli." arXiv:2307.11760. (EmotionPrompt.)
- Li, Kenneth, Oam Patel, Fernanda Viégas, Hanspeter Pfister, Martin Wattenberg. 2023. "Inference-Time Intervention: Eliciting Truthful Answers from a Language Model." NeurIPS 2023. arXiv:2306.03341.
- Lin, Stephanie, Jacob Hilton, Owain Evans. 2022. "TruthfulQA: Measuring How Models Mimic Human Falsehoods." ACL 2022. arXiv:2109.07958.
- Lindsey, Jack. 2025. "Emergent Introspective Awareness in Large Language Models." Transformer Circuits Thread, October 2025. https://transformer-circuits.pub/2025/introspection/. (Research note.)
- Marks, Samuel, Max Tegmark. 2023. "The Geometry of Truth: Emergent Linear Structure in Large Language Model Representations of True/False Datasets." arXiv:2310.06824.
- OpenAI. 2025. "Sycophancy in GPT-4o: What happened and what we're doing about it." OpenAI blog, April 29 2025. https://openai.com/index/sycophancy-in-gpt-4o/. (Industry post-mortem.)
- Pan, Alexander, Lijie Chen, Jacob Steinhardt. 2024. "LatentQA: Teaching LLMs to Decode Activations Into Natural Language." arXiv:2412.08686.
- Park, Kiho, Yo Joong Choe, Victor Veitch. 2024. "The Linear Representation Hypothesis and the Geometry of Large Language Models." ICML 2024 (PMLR 235:39643-39666). arXiv:2311.03658.
- Perez, Ethan, et al. 2022. "Discovering Language Model Behaviors with Model-Written Evaluations." Findings of ACL 2023. arXiv:2212.09251.
- Rimsky, Nina, Nick Gabrieli, Julian Schulz, Meg Tong, Evan Hubinger, Alexander Matt Turner. 2024. "Steering Llama 2 via Contrastive Activation Addition." ACL 2024. arXiv:2312.06681.
- Salewski, Leonard, Stephan Alaniz, Isabel Rio-Torto, Eric Schulz, Zeynep Akata. 2023. "In-Context Impersonation Reveals Large Language Models' Strengths and Biases." NeurIPS 2023 (Spotlight). arXiv:2305.14930.
- Sap, Maarten, Ronan Le Bras, Daniel Fried, Yejin Choi. 2022. "Neural Theory-of-Mind? On the Limits of Social Intelligence in Large LMs." EMNLP 2022. arXiv:2210.13312.
- Sclar, Melanie, Yejin Choi, Yulia Tsvetkov, Alane Suhr. 2024. "Quantifying Language Models' Sensitivity to Spurious Features in Prompt Design or: How I learned to start worrying about prompt formatting." ICLR 2024. arXiv:2310.11324.
- Shanahan, Murray, Kyle McDonell, Laria Reynolds. 2023. "Role-Play with Large Language Models." Nature 623, 493–498. arXiv:2305.16367.
- Shapira, Natalie, Mosh Levy, Seyed Hossein Alavi, Xuhui Zhou, Yejin Choi, Yoav Goldberg, Maarten Sap, Vered Shwartz. 2023. "Clever Hans or Neural Theory of Mind? Stress Testing Social Reasoning in Large Language Models." arXiv:2305.14763.
- Strachan, James W. A., et al. 2024. "Testing theory of mind in large language models and humans." Nature Human Behaviour 8(7):1285–1295.
- Sharma, Mrinank, Meg Tong, Tomasz Korbak, David Duvenaud, Amanda Askell, Samuel R. Bowman, et al. 2023. "Towards Understanding Sycophancy in Language Models." arXiv:2310.13548.
- Subramani, Nishant, Nivedita Suresh, Matthew Peters. 2022. "Extracting Latent Steering Vectors from Pretrained Language Models." Findings of ACL 2022. arXiv:2205.05124.
- Tak, Ala N., Amin Banayeeanzade, Anahita Bolourani, Mina Kian, Robin Jia, Jonathan Gratch. 2025. "Mechanistic Interpretability of Emotion Inference in Large Language Models." Findings of ACL 2025. arXiv:2502.05489.
- Tan, et al. 2024. (Agent personality traits — flagged by Cycle 1 reviewer; full citation pending verification.)
- transformer-circuits.pub. 2026. "Emotion Concepts and their Function in a Large Language Model." Anthropic interpretability research note. https://transformer-circuits.pub/2026/emotions/.
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
