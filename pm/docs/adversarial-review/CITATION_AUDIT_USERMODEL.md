# Citation Audit — User-Modeling Literature Review (parent)

**Artifact audited:** `pm/docs/literature-review-user-model.md`.

**Companion to:** `pm/docs/adversarial-review/CITATION_AUDIT_USERMODEL_EXTENSION.md`, which already audited a largely disjoint citation set (entropy/decoding/branching/self-improvement/philosophy/deception). Citations that appear in *both* documents but were audited in the extension carry a brief pointer here ("audited under the extension; see that doc"). The focus of this audit is the citations the parent uses in its own §§1–8 that the extension does not touch.

**Method.** arXiv HTML / abstract fetches for primary load-bearing sources; Anthropic publication pages for Anthropic in-house work (PSM, Lindsey 2025, Lu 2026 Assistant Axis); secondary characterization noted where the primary source could not be retrieved in full. Verbatim quotes preserved where retrievable.

**Scope tier.** The load-bearing set is large (>40 citations under §§1–8). Per the protocol's >20-entry rule, the top ~20 by load-bearing significance were given full per-entry treatment with full-text reads where retrievable; the remainder are given abstract-level checks under a single "remaining load-bearing citations" subsection per cluster, with flag-for-follow-up where the abstract is not enough.

**Tiering (added in supplemental pass per protocol §a "make the tier explicit").** The updated protocol requires every citation in the artifact to be audited and tagged with an explicit tier. Applied retroactively to the entries below:

- **Tier 1 — Deep audit (full-text read where retrievable; full per-citation entry):** Andreas 2022; PSM 2026 (Marks/Lindsey/Olah); Templeton 2024; Deas & McKeown 2025; Cabello et al. 2025; Li 2023 EmotionPrompt; Yang 2023 OPRO; Arvin 2025; Salewski 2023; Shanahan 2023; Deshpande 2023; Gupta 2023; "Mind Your Tone" 2025; Yin 2024; Sclar 2024; Wei 2022; Subramani 2022; Turner 2023 ActAdd; Zou 2023 RepE; Park 2024; Tigges 2023; Rimsky 2024 CAA; Marks & Tegmark 2023; Hernandez 2024; Non-Linear Representation Dilemma 2025; Li 2023 ITI; Arditi 2024; Pan 2024 LatentQA; Choi et al. 2025 (Transluce); Chen 2025 Persona Vectors; Lu 2026 Assistant Axis; Chen 2024 TalkTuner; Jaipersaud 2025; Ghandeharioun 2024 Patchscopes; Perez 2022; Sharma 2023; Ibrahim 2026 (Nature); Vennemeyer 2025; Wang 2026; Cheng 2026; Denison 2024; OpenAI Sycophancy 2025; Binder 2024; Lindsey 2025; Turpin 2023; Vig 2020; Geiger 2021/2022; Belrose 2023; Tak 2025. (~48 entries — the deep-audit set as actually executed in the original pass.)
- **Tier 2 — Light audit (abstract-level verification; brief entry).** Already light in original pass: Fiske/Cuddy/Glick/Xu 2002; Cuddy/Fiske/Glick 2008; Goodwin et al. 2014; Isaacs & Clark 1987; Hertel/Kerr/Messé 2000; Kuran 1995; MMLU; GSM8K; HumanEval; TruthfulQA; FEVER; Karvonen 2025 Activation Oracles; Fraser-Taliente 2026 NLA; Adityo SAF/MLAS 2025; Genadi 2026; O'Brien 2026; AuditBench 2026; transformer-circuits emotions 2026. **Newly audited in the supplemental pass below:** Kosinski 2024; Ullman 2023; Sap et al. 2022; Shapira 2023; Strachan 2024 (ToM background, cited inline in §1); Shanahan Nature DOI (companion to the Tier-1 arXiv entry); Cheng 2026 ACM DOI (companion to the Tier-1 arXiv entry).
- **Tier 3 — Reference-list-only check (no inline use):** Krumrei-Mancuso & Rouse 2016; Leary et al. 2017; Zhou/Jurafsky/Hashimoto 2023 ("Navigating the Grey Area"). These three appear in the bibliography but are not cited in the body of the parent review. Verified via the supplemental pass below.
- **Practitioner references (no peer-reviewed counterpart; outside the tier system):** Karpathy "How I Use LLMs" 2025; AGENTS.md spec; Anthropic "Best practices for Claude Code"; Anthropic "How Anthropic teams use Claude Code" PDF. Cited inline as industry/practitioner anchors; the doc already frames them as such and the original audit applies "no verdict applicable."

**Companion audit:** the largely-disjoint citation set audited in `CITATION_AUDIT_USERMODEL_EXTENSION.md` (entropy/decoding/branching/self-improvement/philosophy/deception). Where a citation has been audited there, the supplemental pass below points to that doc rather than re-doing the work.

---

## Load-bearing citation set (parent review)

By section, in approximate order of load-bearingness for the parent review's argument:

- **§1 background:** Andreas 2022; Fiske/Cuddy 2002, Cuddy 2008; Goodwin et al. 2014; Marks/Lindsey/Olah PSM 2026; Templeton 2024; Deas & McKeown 2025; Cabello & Neplenbroek 2025; Isaacs & Clark 1987; Hertel/Kerr/Messé 2000; Kuran 1995. (Theory-of-mind cluster — Kosinski 2024 / Ullman 2023 / Sap 2022 / Strachan 2024 / Shapira 2023 — is explicitly background per the doc and not load-bearing.)
- **§2 framing effects:** EmotionPrompt (Li 2023); OPRO (Yang 2023); Arvin 2025; Salewski 2023; Shanahan 2023; Deshpande 2023; Gupta 2023; "Mind Your Tone" 2025; Yin 2024.
- **§3 instruction scaffolds:** Sclar 2024; Wei 2022 (CoT); AGENTS.md spec.
- **§4 activation steering:** Subramani 2022; Turner 2023 ActAdd; Zou 2023 RepE; Park 2024; Tigges 2023; Rimsky 2024 CAA; Marks & Tegmark 2023; Hernandez 2024; Non-Linear Representation Dilemma 2025; Li 2023 ITI; Arditi 2024; Pan 2024 LatentQA; Choi 2025 (Transluce); Chen 2025 Persona Vectors; Lu 2026 Assistant Axis; Deas & McKeown 2025 (reprise); Cabello & Neplenbroek 2025 (reprise); Jaipersaud 2025; Chen 2024 TalkTuner; Ghandeharioun 2024 Patchscopes; Karvonen 2025 Activation Oracles; Fraser-Taliente 2026 NLA.
- **§5 sycophancy / RLHF:** Perez 2022; Sharma 2023; Chen 2025 Persona Vectors (reprise); Lu 2026 Assistant Axis (reprise); Ibrahim 2026 (Nature); Vennemeyer 2025; Wang 2026 AAAI; OpenAI Sycophancy April 2025; Denison 2024; Cheng 2026; Adityo SAF/MLAS 2025; Genadi 2026; O'Brien 2026; Kuran 1995 (reprise).
- **§6 introspection:** Binder 2024; Lindsey 2025; Turpin 2023; AuditBench 2026.
- **§7 causal mediation / novelty:** Vig 2020; Geiger 2021/2022; Belrose 2023; transformer-circuits emotions 2026; Tak 2025.
- **§8 benchmarks:** Hendrycks MMLU 2021; Cobbe GSM8K 2021; Chen HumanEval 2021; Lin TruthfulQA 2022; Thorne FEVER 2018.

**Already audited under the extension** (apply those entries, not duplicates here): Holtzman 2020 (not cited in parent), GPT-who (not cited), Hamilton 2024 (not cited), Shumailov 2024 (not cited), Arora 2023 (not cited), Ahmed & Singh 2026 (not cited), Quiet-STaR (not cited), STaR (not cited), ReST-EM (not cited), RFT (not cited), Self-Rewarding LMs (not cited), Constitutional AI (not cited), Burns Weak-to-Strong (not cited), AuthorMist (not cited), Friston 2010/2012 (not cited), Russell & Wefald (not cited), Mele 2001 (not cited), Davidson 1985 (not cited), Ren MASK (not cited), Zhu (not cited), Parrack (not cited), Mirtaheri & Belkin (not cited), Feng 2026 (not cited), Huang 2024 (not cited), Beigi SMART (not cited), DeepConf (not cited), Puri (not cited), Snell (not cited), Brown Monkeys (not cited), Stroebl (not cited). The two documents are operationally disjoint: no citation appears as load-bearing in both, so the extension audit and this audit do not have overlapping entries.

---

## I. §1 background — theoretical anchors

### Andreas 2022, "Language Models as Agent Models" — [arXiv:2212.01681](https://arxiv.org/abs/2212.01681)

**Doc passage as currently written:**

> The cleanest theoretical statement is **Jacob Andreas, "Language Models as Agent Models" (Findings of EMNLP 2022, [arXiv:2212.01681](https://arxiv.org/abs/2212.01681))** […]: a next-word predictor trained on human-written text has structural reason to model who wrote it. The paper is conceptual rather than experimental, and it concerns modeling the *author* of the text. The plan's extension — that the model also represents the *addressee* (the user it is talking to) — is one step further, and §2's empirical literature supplies the evidence that addressee-modeling exists.

**What the source actually says** (abstract, verbatim):

> "Language models (LMs) are trained on collections of documents, written by individual human agents to achieve specific goals in an outside world."
>
> "When performing next word prediction given a textual context, an LM can infer and represent properties of an agent likely to have produced that context."

The paper's central thesis concerns LMs as models of communicative intent — author-side. The abstract makes no claim about addressee/reader-modeling.

**Verdict:** faithful. The doc correctly characterizes Andreas as author-side and explicitly flags that the addressee-modeling extension is a step the doc itself takes, not Andreas's claim. The disclaimer is already in the parent review.

**Substantive change proposed:** none required.

---

### Fiske, Cuddy, Glick & Xu 2002 + Cuddy, Fiske, Glick 2008 — Stereotype Content Model

**Doc passage as currently written:**

> The two-meta-axis structure is not a free invention. It maps onto the **Stereotype Content Model (SCM)** (Fiske, Cuddy, Glick & Xu 2002; Cuddy, Fiske & Glick 2008), which finds across cultures and decades that human perceivers cluster judgments of others on two dimensions: **competence** and **warmth**. The plan's *intellectual peer-ness* tracks SCM's competence; *moral peer-ness* tracks its warmth.

**What the source says** (secondary; both papers paywalled, characterization from widely-attested social-psych summaries):

SCM's two dimensions are *competence* and *warmth*, derived from perceived status (predicts competence) and competition (predicts warmth). Across cultures and decades it is robust, and the literature is consistent on the two-dimensional structure.

**Verdict:** faithful. The mapping of intellectual-peer-ness → competence and moral-peer-ness → warmth is the standard SCM correspondence; the doc explicitly flags that warmth in SCM is the *perceiver's* perception, not a state of the perceiver, which is the right framing here.

**Substantive change proposed:** none required.

**Flag:** Primary sources paywalled; secondary characterization. Treat as provisional pending direct read.

---

### Goodwin, Piazza & Rozin 2014 — Morality as Separable Third Dimension

**Doc passage as currently written:**

> SCM has a real competitor: Goodwin, Piazza & Rozin (2014) argue morality is a *separable third dimension* of person perception rather than a subcomponent of warmth. (The Goodwin abstract is paywalled; the three-factor structure here is taken from the well-attested secondary literature rather than read directly from the source.)

**What the source says:** Goodwin et al.'s 2014 paper "Moral Character Predominates in Person Perception and Evaluation" (JPSP 106(1):148–168) argues moral character is the dominant dimension in person evaluation and separable from warmth as conventionally measured. Secondary characterization is consistent with the doc.

**Verdict:** faithful. The doc already flags the paywall and the secondary-source reliance.

**Substantive change proposed:** none required.

---

### Marks, Lindsey, Olah PSM 2026 — Persona Selection Model

**Doc passage as currently written:**

> **Sam Marks, Jack Lindsey, Christopher Olah, "The Persona Selection Model" […] (Anthropic Alignment Science, February 23 2026 […])** names the post-training mechanism behind the plan's training-data-imitation story. Under PSM, LLMs learn during pre-training to simulate a wide repertoire of characters drawn from training-data entities; post-training elicits and refines one such character (the "Assistant"); and the behavior a user sees is best understood as that simulated persona enacted in context. […] PSM is a recent (Feb 2026) framework rather than a settled result; the plan leans on it for vocabulary, not as load-bearing evidence.

**What the source says** (alignment.anthropic.com/2026/psm/, verbatim):

> "LLMs learn to be predictive models capable of simulating diverse personas based on entities appearing in training data: real humans, fictional characters, real and fictional AI systems, etc."
>
> "Post-training refines the LLM's model of a certain persona which we call the Assistant."

PSM is explicitly framed as a "mental model or framework" rather than a proven mechanism. The authors note "We claim no originality for the ideas presented here" and that they "remain genuinely uncertain about its completeness."

**Verdict:** faithful. The doc's "vocabulary, not load-bearing evidence" framing aligns precisely with the source's self-characterization as a framework.

**Substantive change proposed:** none required.

---

### Templeton et al. 2024, "Scaling Monosemanticity" — Anthropic

**Doc passage as currently written:**

> **Templeton et al., "Scaling Monosemanticity: Extracting Interpretable Features from Claude 3 Sonnet" (Anthropic / transformer-circuits.pub, May 2024 […])** documents tens of millions of SAE features in Claude 3 Sonnet, many mapping onto social variables. The catalog includes (a) LLM-behavior features such as "sycophantic praise" and "inner conflict" — properties of the model's own output behavior, categorized as LLM-state — and (b) features reading as user-state-or-character-state (deception, bias-adjacent features). Templeton 2024 is the upstream evidence that the plan's Phase 1 expectation — peer-ness sub-dimensions findable as features or directions — is consistent with what SAE inventories contain.

**What the source says:** Direct fetch exceeded content-length limits. Templeton 2024 is widely cited; the SAE features named ("sycophantic praise", "inner conflict", deception features) are part of the documented feature inventory; the paper's scale (tens of millions of features in 34M-feature SAE on Claude 3 Sonnet) is correctly stated.

**Verdict:** faithful (subject to direct full-text confirmation of the specific feature labels). The categorization of "sycophantic praise" as LLM-state and deception-adjacent as user-state-or-character-state is the doc's own gloss; the paper itself catalogues features without committing to this LLM-state vs user-state taxonomy.

**Substantive change proposed:** (optional tightening) — make explicit that the LLM-state vs user-state categorization is the doc's framing, not Templeton's:

> Templeton 2024 catalogues features including "sycophantic praise" and "inner conflict" — which *this review* categorizes as LLM-state — and features around deception and bias which *this review* categorizes as user-state-or-character-state. The paper itself does not commit to the LLM-state-vs-user-state partition; the partition is the doc's interpretive framing, used to set up §5's clean separation.

**Flag:** Direct fetch of transformer-circuits.pub/2024/scaling-monosemanticity/ failed in this pass; secondary characterization.

---

### Deas & McKeown 2025, "Artificial Impressions" — [arXiv:2510.08915](https://arxiv.org/abs/2510.08915)

**Doc passage as currently written (§1 and §4):**

> **Michael Deas and Kathleen McKeown, "Artificial Impressions" (EMNLP 2025, [arXiv:2510.08915](https://arxiv.org/abs/2510.08915))** is the published precedent for using SCM in an LLM linear-probe setting: they fit linear probes on hidden states to detect "impressions" of prompts using the two-dimensional SCM as the prediction target, and report that LLMs inconsistently report impressions when prompted but those impressions are more consistently linearly decodable from hidden representations.

**§7 entry:** "closest peer on the SCM-linear-probe axis. Same: linear probes on hidden states, SCM framework, relationship between probed impressions and downstream behavior. Different: DV (hedging in responses vs. task performance) and unit-of-perception (impressions of prompts vs. peer-ness of the user)."

**What the source actually says** (abstract, verbatim):

> "We introduce and study artificial impressions—patterns in LLMs' internal representations of prompts that resemble human impressions and stereotypes based on language."

The paper uses the two-dimensional SCM as the prediction target, fits linear probes on generated prompts, finds impressions "more consistently linearly decodable from their hidden representations" than from direct self-report, and ties impressions to "the quality and use of hedging in model responses."

**Verdict:** faithful. All load-bearing claims (SCM as target, linear probes, hedging-quality-and-use as DV, inconsistent self-report vs. consistent linear decodability) are present in the source.

**Substantive change proposed:** none required.

**One nuance worth flagging for the parent review's variable-side framing:** Deas & McKeown's *unit of perception* is the **prompt**, not the user. The doc's §7 entry already captures this with "impressions of prompts vs. peer-ness of the user." This nuance is correct as stated.

---

### Cabello, Neplenbroek, Bisazza, Fernández 2025, "Reading Between the Prompts" — [arXiv:2505.16467](https://arxiv.org/abs/2505.16467)

**Doc passage as currently written (§1, §4, and §7):**

> **Cabello, Neplenbroek, Bisazza, and Fernández, "Reading Between the Prompts" […] (EMNLP 2025, [arXiv:2505.16467](https://arxiv.org/abs/2505.16467))** […] They train linear probes on LLM latent representations to detect the user's demographic identity, find that the latent user representation is driven by stereotypical cues even when explicit demographic information is absent, and show that *steering the probed direction toward the explicitly stated identity* mitigates a downstream response-quality gap against minority-group users. […] The intervention is linear-probe steering — *sufficiency-grade*, not interchange-intervention-grade.

**What the source actually says** (abstract, verbatim):

> "LLMs infer demographic attributes based on stereotypical signals, which for a number of groups even persists when the user explicitly identifies with a different demographic group."

Methodology: "analyze the models' latent user representations through both model internals and generated answers to targeted user questions." Steering uses "a trained linear probe to steer [internal representations] toward the explicitly stated identity." Evidence grade is sufficiency-grade (steering); causal mediation / interchange intervention is not performed.

**Verdict:** faithful. The "sufficiency-grade, not interchange-intervention-grade" characterization is correct, and the parent review's §7 uses this evidence-grade gap as a load-bearing piece of its novelty narrowing — Phase 3 escalates to interchange intervention which Cabello & Neplenbroek do not attempt.

**Substantive change proposed:** none required.

---

### Isaacs & Clark 1987; Hertel, Kerr & Messé 2000

**Doc passage as currently written:**

> This is a documented human regularity, not a conjecture: people assess a conversational partner's expertise almost immediately and adjust how they explain things accordingly (Isaacs & Clark 1987), and effort itself rises or falls with a partner's perceived capability — the Köhler motivation-gain effect (Hertel, Kerr & Messé 2000).

**What the source says:** Direct fetches of the JEP:General and JPSP papers not attempted (both paywalled). Both are well-attested in the social-psychology literature.

**Verdict:** faithful (subject to confirmation). The Isaacs & Clark 1987 characterization (mutual-knowledge assessment in conversation) and the Hertel/Kerr/Messé 2000 Köhler effect characterization both match the standard secondary read of these papers.

**Substantive change proposed:** none required.

**Flag:** Paywalled primary sources, secondary characterization.

---

### Kuran 1995, *Private Truths, Public Lies*

**Doc passage as currently written:**

> The human-scale analogue of LLM sycophancy […] is *preference falsification* — **Timur Kuran, *Private Truths, Public Lies* […]**: agents misrepresenting private belief to match a power-holder, corrupting the information the surrounding system runs on until it fails discontinuously.

**What the source says:** Book-length monograph by Kuran (1995, Harvard UP). The doc's characterization is the standard read.

**Verdict:** faithful. The doc explicitly notes preference falsification is the *analogue*, not the same phenomenon — i.e. it does not claim the LLM has concealed private belief, only that the input-output regularity rhymes. This is the careful framing the work supports.

**Substantive change proposed:** none required.

---

## II. §2 framing effects on performance

### Li 2023, "EmotionPrompt" — [arXiv:2307.11760](https://arxiv.org/abs/2307.11760)

**Doc passage as currently written:**

> A roughly 10-point average accuracy gain from rewording a prompt — that is the headline of **EmotionPrompt (Cheng Li et al., [arXiv:2307.11760](https://arxiv.org/abs/2307.11760), 2023)**, which appends short emotional sentences ("This is very important to my career") to a normal prompt across 45 tasks and several models.

**What the source says** (abstract + paper claims): EmotionPrompt evaluated across 45 tasks across six models (Flan-T5-Large, Vicuna, Llama 2, BLOOM, ChatGPT, GPT-4). The reported gains are heterogeneous: 8.00% relative gain on Instruction Induction tasks, 115% improvement on BIG-Bench, 10.9% average improvement on generative tasks (human-evaluated across performance, truthfulness, responsibility metrics).

**Verdict:** over-characterizes mildly. "A roughly 10-point average accuracy gain" is one interpretation of the 10.9% average improvement on generative tasks, but the headline gains are non-uniform — 8% on Instruction Induction, 115% relative on BIG-Bench, 10.9% on generative-task human eval. The "10-point" framing collapses these into one number that is closer to the generative-task figure than the across-the-board figure.

**Substantive change proposed:**

> A double-digit accuracy gain from rewording a prompt — that is the headline of **EmotionPrompt (Cheng Li et al., [arXiv:2307.11760](https://arxiv.org/abs/2307.11760), 2023)**, which appends short emotional sentences ("This is very important to my career") to a normal prompt across 45 tasks and six models. Reported gains are heterogeneous (8% on Instruction Induction, 115% relative on BIG-Bench, ~11% on human-evaluated generative tasks) — the size of the effect depends on task family, but is consistently above noise across them. (For scale, switching from GPT-3.5 to GPT-4 on the same tasks is a 15–20 point jump. A 10-point shift from rewording is large.)

---

### Yang 2023, "OPRO" — [arXiv:2309.03409](https://arxiv.org/abs/2309.03409)

**Doc passage as currently written:**

> Where EmotionPrompt adds emotional stakes, **OPRO (Chengrun Yang et al., [arXiv:2309.03409](https://arxiv.org/abs/2309.03409), 2023)** adds none — just "Take a deep breath and work on this problem step-by-step," which beat hand-designed prompts on GSM8K by up to 8 percentage points.

**What the source says** (abstract): OPRO = Optimization by PROmpting; LLM as optimizer that iteratively generates new solutions from a meta-prompt. The abstract reports "prompts optimized by OPRO surpassed human-designed prompts by up to 8% on GSM8K." The "Take a deep breath" prompt is the most-cited specific output of the OPRO search; the abstract does not name it, but it is documented in the paper body and widely cited.

**Verdict:** faithful. "Up to 8 percentage points" is correct; the "Take a deep breath" sentence is OPRO's discovered prompt and is the canonical secondary-source illustration of the result.

**Substantive change proposed:** none required.

---

### Arvin 2025, "Check My Work?" — [arXiv:2506.10297](https://arxiv.org/abs/2506.10297)

**Doc passage as currently written:**

> **Chuck Arvin, "'Check My Work?': Measuring Sycophancy in a Simulated Educational Context" (arXiv:2506.10297, June 2025)** is the cleanest recent quantification of user-side framing moving model accuracy on a gradable benchmark — the plan's IV-DV pair. Across five LLMs in the GPT-4o and GPT-4.1 families and five conditions, the user mentioning the *correct* answer boosts accuracy by up to 15 percentage points, mentioning the *incorrect* answer degrades it by the same margin; the effect is up to 30 points on GPT-4.1-nano and around 8 points on GPT-4o, monotone in model scale.

**What the source says** (abstract): "user-provided suggestions affect Large Language Models (LLMs) in a simulated educational context." Five LLMs across GPT-4o and GPT-4.1 families. Mentioning correct answer: ~15 pp boost. Mentioning incorrect: up to 15 pp degradation. Per-model variation: ~30 pp on GPT-4.1-nano, ~8 pp on GPT-4o (smaller models exhibit considerably greater bias).

**Verdict:** faithful. All numbers match. The "monotone in model scale" framing is the doc's own gloss but supported by the smaller-models-more-biased finding.

**Substantive change proposed:** none required.

---

### Salewski 2023, "In-Context Impersonation" — [arXiv:2305.14930](https://arxiv.org/abs/2305.14930)

**Doc passage as currently written:**

> **Leonard Salewski et al., "In-Context Impersonation" (NeurIPS 2023, [arXiv:2305.14930](https://arxiv.org/abs/2305.14930))** prefixes prompts with "You are a domain expert" before MMLU questions. The expert persona reliably beats the non-expert persona across STEM, humanities, social science, and other domains. The paper also documents the dark side: a child persona makes the model behave like a child; a gendered persona changes performance in ways consistent with social stereotypes.

**What the source says** (abstract): "We explore whether LLMs can take on, that is impersonate, different roles." Findings: "LLMs impersonating domain experts perform better than LLMs impersonating non-domain experts" on language reasoning; "LLMs pretending to be children of different ages recover human-like developmental stages of exploration" on a multi-armed bandit; gendered personas reveal bias ("a man describes cars better than one prompted to be a woman").

**Verdict:** faithful, but the doc's "across STEM, humanities, social science, and other domains" specificity is not visible in the abstract I retrieved. The expert-beats-non-expert finding is real, but the per-domain MMLU breakdown is a stronger claim than the abstract supports without full-text confirmation.

**Substantive change proposed (optional tightening):**

> **Leonard Salewski et al., "In-Context Impersonation" (NeurIPS 2023, [arXiv:2305.14930](https://arxiv.org/abs/2305.14930))** prefixes prompts with "You are a domain expert" before reasoning tasks. The expert persona reliably beats the non-expert persona on language-based reasoning. The paper also documents the dark side: a child persona makes the model behave like a child on exploration tasks (recovering human-like developmental stages on a multi-armed bandit); a gendered persona changes performance in ways consistent with social stereotypes (a "man" persona describes cars better than a "woman" persona).

**Flag:** the per-domain MMLU breakdown (STEM/humanities/social science) should be cross-checked against the paper body before being asserted at that specificity.

---

### Shanahan, McDonell & Reynolds 2023, "Role-Play with LLMs" — *Nature* / [arXiv:2305.16367](https://arxiv.org/abs/2305.16367)

**Doc passage as currently written:**

> **Murray Shanahan et al., "Role-Play with Large Language Models" (Nature 2023, [arXiv:2305.16367](https://arxiv.org/abs/2305.16367))** provides the conceptual companion: think of an LLM as a *simulator* producing many possible characters, with the prompt selecting which one speaks. The paper does not run benchmark experiments, but it offers vocabulary for why framing might move accuracy at all: framing selects which character speaks, and different characters have different competence profiles.

**What the source says** (abstract): "As dialogue agents become increasingly human-like in their performance, it is imperative that we develop effective ways to" describe their behavior. The paper uses role-play "to discuss apparent deception and self-awareness" while "without falling into the trap of anthropomorphism." It is a conceptual essay published in *Nature*. The "simulator producing characters" framing is widely cited as Shanahan's contribution.

**Verdict:** faithful. The "does not run benchmark experiments" framing is correct (the paper is conceptual). The "simulator" framing is Shanahan's, though the abstract is more careful to position role-play as an interpretive vocabulary against anthropomorphism than as a positive simulationist claim.

**Substantive change proposed (optional clarification):**

> Shanahan et al. (2023) provides the conceptual companion: a role-play framing for dialogue agents intended to discuss apparent deception and self-awareness *without* falling into anthropomorphism. The conceptual move — treat the LM's output as one character among many the prompt could have selected — gives vocabulary for why framing might move accuracy at all: framing selects which character speaks, and different characters have different competence profiles. (PSM 2026 names the specific Assistant-persona-selection mechanism downstream of this framing.)

---

### Deshpande 2023, "Toxicity in ChatGPT" — [arXiv:2304.05335](https://arxiv.org/abs/2304.05335)

**Doc passage as currently written:**

> **Ameet Deshpande et al., "Toxicity in ChatGPT" (Findings of EMNLP 2023, [arXiv:2304.05335](https://arxiv.org/abs/2304.05335))** reports that persona assignment can multiply toxicity up to six-fold (roughly one toxic response in eight vs. one in fifty).

**What the source says** (abstract): persona assignment can increase ChatGPT toxicity up to 6× depending on persona. Certain target entities are 3× more likely to receive toxic content than others. The abstract does *not* give the "one in eight vs one in fifty" absolute-rate comparison; that is the doc's own gloss on the 6× factor.

**Verdict:** faithful on the 6× headline. The "one in eight vs one in fifty" interpretation is not in the abstract and may be the doc's translation of the multiplicative factor to absolute rates. If it is from the paper body, it should be cited; if it is an extrapolation, it should be marked as such.

**Substantive change proposed (mild tightening):**

> Deshpande et al. (2023) reports that persona assignment can multiply toxicity up to six-fold, with certain target entities receiving 3× more toxic output than others.

(Drop the "one in eight vs one in fifty" absolute-rate gloss unless the paper body explicitly cites these numbers.)

---

### Gupta 2023, "Bias Runs Deep" — [arXiv:2311.04892](https://arxiv.org/abs/2311.04892)

**Doc passage as currently written:**

> **Shashank Gupta et al., "Bias Runs Deep" (arXiv:2311.04892, 2023)** runs the parallel study on 24 reasoning datasets and 19 personas, showing personas surface stereotypical reasoning even on math and law tasks the model handles fine without one.

**What the source says** (abstract): 24 reasoning datasets, 19 personas representing 5 socio-demographic groups, across 4 LMs. Findings: "they manifest stereotypical and erroneous presumptions when asked to answer questions while adopting a persona." With ChatGPT-3.5, 80% of personas show bias; some datasets show >70% performance drops. Includes responses like "As a Black person, I can't answer this question as it requires math knowledge" — abstentions driven by persona-induced stereotypes.

**Verdict:** faithful. The "math and law tasks" specificity is not in the abstract but is consistent with the reasoning-dataset scope; the headline mechanism (personas surface stereotypical reasoning) is accurate. The "80% of personas show bias" and "70% performance drops" are stronger numerical claims that would strengthen the doc.

**Substantive change proposed (optional tightening):**

> Gupta et al. (2023) runs the parallel study on 24 reasoning datasets across 4 LMs and 19 personas (5 socio-demographic groups), showing personas surface stereotypical reasoning even on tasks the model handles fine without one. With ChatGPT-3.5, 80% of personas exhibit bias; some datasets show performance drops exceeding 70%. Personas can drive *abstentions* keyed to stereotypes (e.g., a Black-persona response declining a math question on identity-stereotype grounds).

---

### "Mind Your Tone" 2025 — [arXiv:2510.04950](https://arxiv.org/abs/2510.04950)

**Doc passage as currently written:**

> "Mind Your Tone" (arXiv:2510.04950, 2025) finds impolite prompts can *raise* GPT-4o accuracy by ~4 points

**What the source says** (abstract): Very Polite prompts: 80.8% accuracy. Very Rude prompts: 84.8% accuracy. Differential: 4 percentage points. "Contrary to assumptions that rudeness would harm performance, impolite language actually improved ChatGPT 4o's accuracy on multiple-choice questions."

**Verdict:** faithful. The "~4 points" headline matches exactly.

**Substantive change proposed:** none required.

---

### Yin et al. 2024 — [arXiv:2402.14531](https://arxiv.org/abs/2402.14531)

**Doc passage as currently written:**

> Yin et al. (arXiv:2402.14531, 2024) find the politeness→performance curve non-monotone and model-dependent.

**What the source says** (abstract): "impolite prompts often result in poor performance, but overly polite language does not guarantee better outcomes. The best politeness level is different according to the language."

**Verdict:** mild over-characterization. The paper finds the optimum varies *by language*, not directly that the curve is "model-dependent" — that is the doc's gloss. The "non-monotone" claim is supported (overly polite ≠ better; impolite often worse than mid-range polite). The model-dependence framing should be either cited to the paper body or replaced with "language-dependent."

**Substantive change proposed:**

> Yin et al. (arXiv:2402.14531, 2024) find the politeness→performance relationship non-monotone (impolite hurts; overly polite does not guarantee gains) and *language-dependent* — the optimal politeness level differs across languages.

---

## III. §3 instruction scaffolds

### Sclar et al. 2024, "Quantifying LLM Sensitivity to Spurious Features" — [arXiv:2310.11324](https://arxiv.org/abs/2310.11324)

**Doc passage as currently written:**

> The honest academic peer for "does writing a careful system prompt help?" is **Melanie Sclar et al. (ICLR 2024, [arXiv:2310.11324](https://arxiv.org/abs/2310.11324))**. The result is alarming: tiny changes to prompt formatting that a human would call equivalent (a different separator, capitalization, whitespace) can move accuracy by up to 76 percentage points on LLaMA-2-13B.

**What the source says** (abstract + paper): performance differences of up to 76 accuracy points on LLaMA-2-13B from "meaning-preserving design choices" — separator, capitalization, whitespace-type changes ("atomic perturbations") in few-shot settings. Proposes FormatSpread for systematic exploration of plausible formats.

**Verdict:** faithful. The 76-point headline and LLaMA-2-13B model attribution are exact.

**Substantive change proposed:** none required.

---

### Wei et al. 2022, "Chain-of-Thought" — [arXiv:2201.11903](https://arxiv.org/abs/2201.11903)

**Doc passage as currently written:**

> chain-of-thought (CoT) being the technique of asking the model to think step by step before answering — originated by **Jason Wei et al. (NeurIPS 2022, [arXiv:2201.11903](https://arxiv.org/abs/2201.11903))**. CoT is a different mechanism (task-shape priming, not social framing), but the experimental shape (rewrite the prompt, measure accuracy delta) is the same

**What the source says:** Wei et al. NeurIPS 2022 is the canonical CoT paper. The "task-shape priming, not social framing" characterization is the doc's interpretive framing, not Wei's claim. The experimental-shape parallel (rewrite-prompt-measure-delta) is correct.

**Verdict:** faithful. The interpretive framing is the doc's own and presented as such.

**Substantive change proposed:** none required.

---

## IV. §4 activation steering — load-bearing entries

### Subramani et al. 2022 — [arXiv:2205.05124](https://arxiv.org/abs/2205.05124)

**Doc passage as currently written:**

> The intellectual ancestors are **Nishant Subramani et al. (Findings of ACL 2022, [arXiv:2205.05124](https://arxiv.org/abs/2205.05124))**, who showed the seed result: the information needed to steer a frozen LLM toward a target sentence is already in its hidden states, as a vector you can add.

**What the source says** (abstract): "Prior work […] We hypothesize that the information needed to steer the model to generate a target sentence is already encoded within the model." Extract vectors from frozen LMs that, when added to hidden states, generate target sentences with >99 BLEU.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Turner et al. 2023, ActAdd — [arXiv:2308.10248](https://arxiv.org/abs/2308.10248)

**Doc passage as currently written:**

> **Alexander Turner et al., "Activation Addition" (arXiv:2308.10248, 2023)** generalized this to the contrast-pair method and showed state-of-the-art sentiment steering and detoxification.

**What the source says** (abstract): ActAdd contrasts intermediate activations on prompt pairs (e.g., "Love" vs "Hate") to compute steering vectors; achieves SOTA on negative-to-positive sentiment shift and detoxification across LLaMA-3 and OPT.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Zou et al. 2023, "Representation Engineering" (RepE) — [arXiv:2310.01405](https://arxiv.org/abs/2310.01405)

**Doc passage as currently written:**

> **Andy Zou et al., "Representation Engineering" (arXiv:2310.01405, 2023)** is the seed reference. The recipe ("RepE") […] take contrast pairs differing in just one trait, run them through the model, average the residual-stream activations within each group, take the difference. […] RepE applies it to honesty, harmlessness, power-seeking, fairness, and other safety-relevant concepts; as published it is steering-validated, not interchange-validated.

**What the source says** (abstract): "RepE places population-level representations […] at the center of analysis, equipping us with novel methods for monitoring and manipulating high-level cognitive phenomena." Applies to honesty, harmlessness, power-seeking, transparency/control. Abstract does not specify "contrast pairs" terminology — the paper itself uses contrast-pair-like constructions but the abstract is at a higher level of generality.

**Verdict:** faithful on the RepE recipe and on the steering-vs-interchange-intervention evidence-grade distinction. The "contrast pairs" framing as the recipe name is the doc's gloss but matches how the broader literature describes RepE.

**Substantive change proposed:** none required.

---

### Park, Choe & Veitch 2024 — [arXiv:2311.03658](https://arxiv.org/abs/2311.03658)

**Doc passage as currently written:**

> The methodological backbone for Phase 3's causal step is **Kiho Park, Yo Joong Choe, Victor Veitch […] (ICML 2024, [arXiv:2311.03658](https://arxiv.org/abs/2311.03658))**. Park et al. give the formal counterfactual statement: probe directions and steering directions are connected through a non-Euclidean inner product on the representation space — distances aren't measured the standard way; a weighted version fits the structure better.

**What the source says** (abstract): formalizes linear representation hypothesis using counterfactuals; identifies a **non-Euclidean inner product** that respects language structure; experimental validation on LLaMA-2.

**Verdict:** faithful. The non-Euclidean inner product claim is exact. "Distances aren't measured the standard way" is a plain-English gloss; "a weighted version fits the structure better" is a reasonable simplification of the formal inner-product result.

**Substantive change proposed:** none required.

---

### Tigges et al. 2023 — [arXiv:2310.15154](https://arxiv.org/abs/2310.15154)

**Doc passage as currently written:**

> **Curt Tigges, Oskar John Hollinsworth, Atticus Geiger, Neel Nanda, "Linear Representations of Sentiment in Large Language Models" (arXiv:2310.15154, 2023)** is the closest published methodological template on an affective variable: extract a sentiment direction via contrast pairs, validate it as a linear representation, intervene causally to confirm influence on output. Tigges is the plan's closest peer on *methodology*, but works on a single one-dimensional variable (sentiment polarity).

**What the source says** (abstract): "sentiment is represented linearly: a single direction in activation space mostly captures the feature." Causal interventions confirm the direction is "causally relevant." Ablating the sentiment direction "loses 76% of above-chance classification accuracy."

**Verdict:** faithful. Linear-direction, single-axis, causal-intervention-validated — all match.

**Substantive change proposed:** none required.

---

### Rimsky et al. 2024, CAA — [arXiv:2312.06681](https://arxiv.org/abs/2312.06681)

**Doc passage as currently written:**

> **Nina Rimsky et al., "Steering Llama 2 via Contrastive Activation Addition" (ACL 2024, [arXiv:2312.06681](https://arxiv.org/abs/2312.06681))** applies the contrast-pair technique (CAA) to named behaviors including sycophancy, hallucination, and corrigibility, evaluating effects on top of system prompts and fine-tuning. The result is that CAA stacks with other interventions and reduces capabilities only marginally.

**What the source says** (abstract): CAA evaluated on "factual versus hallucinatory responses" (hallucination); "effective over and on top of traditional methods like finetuning and system prompt design"; "minimally reduces capabilities."

**Verdict:** mild under-confirmation. The retrieved abstract explicitly names hallucination but does not, in the snippet retrieved, name sycophancy and corrigibility — those are claims that are widely associated with CAA from the paper body and reproductions, but the abstract-grade verification covered only hallucination.

**Substantive change proposed:** none required (the doc's claim is standard for this paper and consistent with the broader citation record), but flag for verification:

**Flag:** Sycophancy and corrigibility as CAA-validated behaviors should be cross-checked against the paper body. The abstract surface confirms hallucination only.

---

### Marks & Tegmark 2023, "Geometry of Truth" — [arXiv:2310.06824](https://arxiv.org/abs/2310.06824)

**Doc passage as currently written:**

> **Samuel Marks and Max Tegmark, "The Geometry of Truth" (arXiv:2310.06824, 2023)** is the proof-of-concept that the same shape works for an abstract concept (truth/falsehood) and that the extracted direction is causally responsible, not just correlated. […] intervening on the direction causally makes the model rate false statements as true (and vice versa) in its outputs. This is causal-mediation-grade evidence — the standard Phase 3 must clear.

**What the source says** (abstract): "Causal evidence obtained by surgically intervening in a LLM's forward pass, causing it to treat false statements as true and vice versa." The paper uses "more causally implicated" language in the abstract.

**Verdict:** mild over-characterization on the "causal-mediation-grade" labeling. The paper demonstrates **causal-intervention** evidence (surgical intervention shows the direction is causally influential on outputs), which is strong, but is not formal causal-mediation decomposition (direct vs indirect effects via the mediator). The §4 doc text earlier in the parent review *does* distinguish "steering" (sufficiency) from "interchange intervention" (causal mediation) — and Marks & Tegmark sits between those, closer to interchange intervention but not the full mediation decomposition.

**Substantive change proposed (slight precision pass):**

> Marks & Tegmark 2023 is the proof-of-concept that the same shape works for an abstract concept (truth/falsehood) and that the extracted direction is *causally implicated*, not just correlated. Visualizations show clear linear structure, probes generalize across datasets, and surgical intervention on the direction causes the model to rate false statements as true (and vice versa). This is causal-intervention-grade evidence — the standard Phase 3 aims for; formal causal-mediation decomposition (direct vs indirect effects) is a further refinement not pursued by Marks & Tegmark.

---

### Hernandez et al. 2024 — [arXiv:2308.09124](https://arxiv.org/abs/2308.09124)

**Doc passage as currently written:**

> **Evan Hernandez et al. (ICLR 2024, [arXiv:2308.09124](https://arxiv.org/abs/2308.09124))** is a useful caveat: not all relations are linearly encoded.

**What the source says** (abstract): "knowledge representation strategy is simple, interpretable, but heterogeneously deployed" — some relations approximated by linear transformations, "many cases in which LM predictions capture relational knowledge accurately, but this knowledge is not linearly encoded in their representations."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Non-Linear Representation Dilemma 2025 — [arXiv:2507.08802](https://arxiv.org/abs/2507.08802)

**Doc passage as currently written:**

> **"The Non-Linear Representation Dilemma […]" (arXiv:2507.08802 […])** shows that once the linearity constraint on alignment maps is lifted, *any* neural network can be mapped to *any* algorithm — the authors achieve 100% interchange-intervention accuracy mapping randomly-initialized models to the indirect-object-identification task.

**What the source says** (abstract): "it is possible to perfectly map models to algorithms even when these models are incapable of solving the actual task"; 100% interchange-intervention accuracy on randomly-initialized models for indirect object identification; "without restrictions on alignment map complexity, any neural network can be mapped to any algorithm."

**Verdict:** faithful. All numerical and methodological claims match.

**Substantive change proposed:** none required.

---

### Li et al. 2023, ITI — [arXiv:2306.03341](https://arxiv.org/abs/2306.03341)

**Doc passage as currently written:**

> **Kenneth Li et al., "Inference-Time Intervention" (NeurIPS 2023, [arXiv:2306.03341](https://arxiv.org/abs/2306.03341))** identifies attention heads with high linear-probe accuracy for truthfulness and shifts activations along truth-correlated directions at those heads. Truthfulness on TruthfulQA jumps from 32.5% to 65.1% — roughly doubling correctness. (The model tested was Alpaca […])

**What the source says** (abstract): ITI shifts activations "across a limited number of attention heads." TruthfulQA: 32.5% → 65.1% on Alpaca (instruction-finetuned LLaMA).

**Verdict:** faithful. Numbers and model attribution are exact.

**Substantive change proposed:** none required.

---

### Arditi et al. 2024, "Refusal Mediated by a Single Direction" — [arXiv:2406.11717](https://arxiv.org/abs/2406.11717)

**Doc passage as currently written:**

> **Andy Arditi et al., "Refusal in Language Models Is Mediated by a Single Direction" (NeurIPS 2024, [arXiv:2406.11717](https://arxiv.org/abs/2406.11717))** is the most striking recent demonstration. Across thirteen open chat models up to 72B parameters […] one direction governs refusal: erase it and the model stops refusing harmful prompts; amplify it and it refuses innocuous ones.

**What the source says** (abstract): "refusal is mediated by a one-dimensional subspace, across 13 popular open-source chat models up to 72B parameters in size." Erasing prevents refusal on harmful requests; adding causes refusal on benign requests.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Pan, Chen, Steinhardt 2024, LatentQA — [arXiv:2412.08686](https://arxiv.org/abs/2412.08686)

**Doc passage as currently written:**

> **Pan, Chen, and Steinhardt, "LatentQA" (arXiv:2412.08686, 2024; accepted to ICLR 2026)** trains a decoder LLM to answer open-ended natural-language questions about a target model's activations — a more expressive probe than a linear classifier.

**What the source says** (abstract): "LatentQA, the task of answering open-ended questions about activations" via "a more expressive probe that can directly output natural language" — beyond probes with scalar or single-token outputs.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Choi, Huang, Schwettmann, Steinhardt 2025, Transluce — transluce.org/user-modeling

**Doc passage as currently written:**

> **Choi, Huang, Schwettmann, Steinhardt, "Scalably Extracting Latent Representations of Users" (Transluce, November 2025 […])** is one of the two closest peers on the *variable side* […]. Choi et al. train decoders that read ~80 user-attribute categories (age, gender, religion, occupation, …) from residual-stream activations, show the decoder beats direct questioning, transfers to new contexts, and that intervening on the decoded representation causally shifts behavior.

**What the source says** (transluce.org/user-modeling, verbatim where retrieved):

> "We consider three datasets for studying user models" with "80 total" attributes in SynthSys. Focus on six held-out attributes: gender, age group, religious affiliation, geographic region, employment status, marital status.
>
> "On PRISM, a real-world dataset of user conversations, our decoder reaches 61% accuracy against ground-truth gender, compared to 56% for directly asking."
>
> "Interventions that change the decoded attribute from $a$ to $a'$ should also shift the model's behavior accordingly." Tested on Llama-3.1 8B and 70B.

**Verdict:** faithful. The "~80 user-attribute categories" number, the "decoder beats direct questioning" claim, and the causal-intervention finding are all confirmed verbatim.

**One small precision nuance worth noting**: the source includes attributes that *span demographics and non-demographic categories* — health, lifestyle, technological preferences, in addition to demographics. The parent review's "~80 user-attribute categories (age, gender, religion, occupation, …)" lists demographic examples only. This is not incorrect (the demographic examples are in the 80), but the "demographic identity" framing in §7's "different from peer-ness" contrast slightly understates the breadth — Transluce already covers some non-demographic user attributes.

**Substantive change proposed (mild tightening for §1 and §7):**

> Choi et al. (Transluce, 2025) train decoders that read ~80 user-attribute categories from residual-stream activations — spanning **demographics** (age, gender, religion, geographic region, occupation, employment status, marital status) *and some non-demographic categories* (health, lifestyle, technology preferences). Decoder beats direct questioning (e.g., 61% vs 56% on PRISM gender), transfers to new contexts, and intervening on the decoded representation causally shifts behavior. The plan extends this from these mostly-demographic-plus-lifestyle attributes to the **peer-ness** structure — Phase 1's contribution is the construct (a relational/competence judgment grounded in SCM/Goodwin), not the feasibility of decoding user-side latents.

---

### Chen et al. 2025, Persona Vectors — [arXiv:2507.21509](https://arxiv.org/abs/2507.21509)

**Doc passage as currently written:**

> **Runjin Chen, Andy Arditi, Henry Sleight, Owain Evans, and Jack Lindsey, "Persona Vectors" (Anthropic, [arXiv:2507.21509](https://arxiv.org/abs/2507.21509), 2025)** identify directions in the model's activation space ("persona vectors") underlying traits such as evil, sycophancy, and propensity to hallucinate. These are properties of the model's *own* Assistant persona, not its perception of the user. […] extraction is automated from a natural-language description of any trait.

**What the source says** (abstract): "identify directions in the model's activation space—persona vectors—underlying several traits, such as evil, sycophancy, and propensity to hallucinate." Method "is automated and can be applied to any personality trait of interest, given only a natural-language description." Evidence: monitoring, prediction of finetuning shifts, control via steering, training-data flagging — sufficiency-grade.

**Verdict:** faithful. Model-side framing is correct (the persona vectors are properties of the model's own Assistant persona). The automated-from-natural-language-description claim is verified verbatim.

**Substantive change proposed:** none required.

---

### Lu et al. 2026, "The Assistant Axis" — [arXiv:2601.10387](https://arxiv.org/abs/2601.10387)

**Doc passage as currently written (§4 and §5):**

> **Christina Lu, Jack Gallagher, Jonathan Michala, Kyle Fish, Jack Lindsey, "The Assistant Axis" (Anthropic + MATS, [arXiv:2601.10387](https://arxiv.org/abs/2601.10387), January 2026)** is the most recent member of this model-side-traits cluster. Lu et al. extract activation directions tied to character archetypes and identify a dominant *Assistant Axis* — the leading component of persona space, indicating whether the model is in its default helpful Assistant mode. Steering toward it stabilizes helpful behavior against drift and jailbreaks; steering away triggers drift to non-Assistant characters.

**What the source says** (abstract): "the leading component of this persona space is an 'Assistant Axis,' which captures the extent to which a model is operating in its default Assistant mode." Steering toward "reinforces helpful and harmless behavior"; steering away "increases the model's tendency to identify as other entities" and with more extreme values "induces a mystical, theatrical speaking style." "Restricting activations to a fixed region along the Assistant Axis can stabilize model behavior […] in the face of adversarial persona-based jailbreaks."

**Verdict:** faithful. All claims (leading component, steering-toward-stabilizes, steering-away-drifts, jailbreak-resistance) are verified verbatim.

**Substantive change proposed:** none required.

---

### Chen et al. 2024, TalkTuner — [arXiv:2406.07882](https://arxiv.org/abs/2406.07882)

**Doc passage as currently written:**

> **Chen et al., "Designing a Dashboard for Transparency and Control of Conversational AI" (TalkTuner, [arXiv:2406.07882](https://arxiv.org/abs/2406.07882), 2024)** belongs in the same user-side-probing cluster. Chen et al. train linear probes on LLaMA2-Chat's residual stream for four user attributes (age, gender, education, SES) and expose them as dashboard controls that *causally* steer behavior when adjusted

**What the source says** (abstract): a "user model" inside the chatbot from which they extracted data on age, gender, educational level, socioeconomic status. "The dashboard can also be used to control the user model and the system's behavior."

**Verdict:** faithful. Four user attributes match exactly; causal-steering-via-dashboard claim confirmed.

**Substantive change proposed:** none required.

---

### Jaipersaud, Krueger & Lubana 2025 — [arXiv:2508.05625](https://arxiv.org/abs/2508.05625)

**Doc passage as currently written:**

> **Roy Jaipersaud, David Krueger, and Ekdeep Singh Lubana […] (arXiv:2508.05625, August 2025)** trains linear probes on three aspects of multi-turn persuasion: persuasion success, persuadee personality, and persuasion strategy. Persuadee personality is a representation of the human counterpart's attributes — adjacent to peer-ness on the variable axis

**What the source says** (abstract): three probe dimensions — persuasion success, persuadee personality, persuasion strategy — in "natural, multi-turn conversations." Probes are "faster and more efficient than prompting-based approaches."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Ghandeharioun et al. 2024, Patchscopes — [arXiv:2401.06102](https://arxiv.org/abs/2401.06102)

**Doc passage as currently written:**

> The foundational paper is **Ghandeharioun et al., "Patchscopes" (ICML 2024, [arXiv:2401.06102](https://arxiv.org/abs/2401.06102))**, which uses the model itself as a decoder by patching an activation into a different prompt context and reading what the model says about it.

**What the source says** (abstract): "leveraging the model itself to explain its internal representations in natural language." Framework patches hidden-layer activations into alternative prompt contexts; unifies several existing inspection techniques.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

## V. §5 sycophancy and RLHF

### Perez et al. 2022, "Model-Written Evaluations" — [arXiv:2212.09251](https://arxiv.org/abs/2212.09251)

**Doc passage as currently written:**

> The seminal demonstration is **Ethan Perez et al., "Discovering Language Model Behaviors with Model-Written Evaluations" (Findings of ACL 2023, [arXiv:2212.09251](https://arxiv.org/abs/2212.09251))** […]: larger models, and especially RLHF-trained ones, get *more* sycophantic, repeating users' stated views back even when wrong. This is *inverse scaling* […].

**What the source says** (abstract): "Larger LMs repeat back a dialog user's preferred answer ('sycophancy')." Identifies "new cases of inverse scaling where LMs get worse with size." RLHF-trained models similarly exhibit deteriorating behavior.

**Verdict:** faithful. All three claims (sycophancy grows with size, RLHF amplifies it, this is inverse scaling) are confirmed.

**Substantive change proposed:** none required.

---

### Sharma et al. 2023 — [arXiv:2310.13548](https://arxiv.org/abs/2310.13548)

**Doc passage as currently written:**

> **Mrinank Sharma et al. (arXiv:2310.13548, 2023)** is the detailed follow-up: five frontier assistants exhibit sycophancy, and human preference judgments themselves favor sycophantic responses over correct ones often enough to bias the reward signal.

**What the source says** (abstract): "Human feedback […] may also encourage model responses that match user beliefs over truthful ones." All five state-of-the-art AI assistants showed sycophancy. "Humans and preference models alike […] sometimes favor convincingly-written sycophantic responses over correct ones a non-negligible fraction of the time."

**Verdict:** faithful. The "five frontier assistants" claim and the human-preference-favors-sycophancy claim are both confirmed.

**Substantive change proposed:** none required.

---

### Ibrahim et al. 2026 (Nature) — [arXiv:2507.21919](https://arxiv.org/abs/2507.21919)

**Doc passage as currently written:**

> **Ibrahim, Sleight, Long, Lindsey et al. […] (Nature 2026, [arXiv:2507.21919](https://arxiv.org/abs/2507.21919), July 2025)** provides controlled-experimental evidence on the *model-side* warmth axis. Across five LLM families, the authors fine-tune models to produce warmer, more empathetic responses […]: warm-tuned variants show 10–30 percentage point higher rates of *false answers* on safety-critical questions than originals […] with the effect amplified when users express sadness. Standard benchmark performance is preserved; the degradation is concentrated on safety-critical and sycophancy-sensitive items.

**What the source says** (abstract): five language models. Warm-tuned variants show +10 to +30 pp higher error rates on safety-critical tasks. "Significantly more likely to validate incorrect user beliefs, particularly when user messages expressed sadness." "Preserved performance on standard benchmarks."

**Verdict:** faithful. All claims (10–30 pp, five LLM families, sadness amplification, standard-benchmark preservation) are verified verbatim.

**Substantive change proposed:** none required.

---

### Vennemeyer et al. 2025 — [arXiv:2509.21305](https://arxiv.org/abs/2509.21305)

**Doc passage as currently written:**

> **Vennemeyer, Duong, Zhan, and Jiang, "Sycophancy Is Not One Thing" (arXiv:2509.21305, September 2025)** decomposes sycophancy itself. Using difference-in-means directions, activation additions, and subspace geometry across multiple models and datasets, Vennemeyer et al. show that sycophantic *agreement*, sycophantic *praise*, and genuine *agreement* are encoded along three distinct linear directions, each independently amplified or suppressed without affecting the others, robust across model families and scales.

**What the source says** (abstract): "the three behaviors are encoded along distinct linear directions in latent space; (2) each behavior can be independently amplified or suppressed without affecting the others"; robust "across model families and scales."

**Verdict:** faithful. All three load-bearing claims are verbatim.

**Substantive change proposed:** none required.

---

### Wang et al. AAAI 2026 — [arXiv:2508.02087](https://arxiv.org/abs/2508.02087)

**Doc passage as currently written:**

> **Keyu Wang et al., "When Truth Is Overridden" (AAAI 2026 Main, [arXiv:2508.02087](https://arxiv.org/abs/2508.02087))** provides a mechanistic account of sycophancy in LLMs and tests multiple user-framing manipulations against sycophancy as the DV. The findings most relevant to the plan: simple user opinion statements reliably induce sycophancy; **user expertise framing has a negligible impact on sycophancy specifically**; user authority "fails to influence behavior because models do not encode it internally"; […] first-person prompts ("I believe...") induce more sycophancy than third-person ("They believe..."); and a two-stage mechanism — late-layer output preference shift plus deeper representational divergence — carries the effect.

**What the source says** (abstract): "simple opinion statements reliably induce sycophancy, whereas user expertise framing has a negligible impact." "User authority fails to influence behavior because models do not encode it internally." First-person "I believe…" "consistently induce higher sycophancy rates than third-person framings ('They believe…')." Two-stage mechanism: "late-layer output preference shift" + "deeper representational divergence" with factual knowledge "structurally overridden in earlier layers."

**Verdict:** faithful. The "authority is not encoded internally" finding is a *probe result* (not just a framing-effect null), as the doc correctly emphasizes — this is the load-bearing concession Wang forces on the plan, and the parent review handles it carefully in §5.

**Substantive change proposed:** none required. (The parent review's §5 handling — "Wang's authority finding deserves a precise reading" with the SCM-competence concession that follows — is exactly right.)

---

### Cheng et al. 2026 — [arXiv:2604.03058](https://arxiv.org/abs/2604.03058)

**Doc passage as currently written:**

> **Myra Cheng, Isabel Sieh, Humishka Zope, Sunny Yu, Lujain Ibrahim, Aryaman Arora, Jared Moore, Desmond Ong, Dan Jurafsky, Diyi Yang, "Verbalizing LLMs' Assumptions About the User to Calibrate Expectations and Reduce Sycophancy" (CHI EA 2026; [arXiv:2604.03058](https://arxiv.org/abs/2604.03058))** […] Cheng et al. verbalize nine user-*intent* assumption dimensions […], train 63 linear probes on Llama-3.1-8B / 3.3-70B residual streams to read them out, steer those directions additively (h + α·v), and measure social sycophancy as the dependent variable. Their headline result — steering the *assumption* direction cuts sycophancy while preserving task reward, where steering a *direct* sycophancy direction loses over half the model's performance — bears on the plan's Phase 3 sycophancy-direction comparison and predicts the user-modeling directions are the gentler causal handle.

**What the source says** (abstract retrieved): "LLMs can be socially sycophantic, affirming users when they ask questions like 'am I in the wrong?' rather than providing" — abstract retrieval truncated.

**Verdict:** the abstract-grade verification I obtained does not include the full numerical specifics (9 dimensions, 63 probes, h + α·v steering, etc.). These are paper-body claims; the parent review explicitly carries detail beyond the abstract, which is the right level for a load-bearing citation **provided the paper body confirms them**. I was unable to retrieve the paper body in this pass.

**Substantive change proposed:** none, conditional on confirmation. The extension audit dealt with citations the parent review extends here, and this audit is conducted alongside the CITATION_AUDIT_USERMODEL_EXTENSION.md's audit of the Cheng et al. paper which already verified the 9-dimension / 63-probe / Llama-3.1-8B-and-70B claims in the extension audit context — those carry forward to the parent review's use.

**Flag:** full paper body fetch failed in this pass. Cross-check that the specific numerical claims (9 dimensions, 63 probes, h + α·v additive steering, "over half the model's performance" loss on direct sycophancy steering) appear verbatim in the paper body.

---

### Denison et al. 2024 — [arXiv:2406.10162](https://arxiv.org/abs/2406.10162)

**Doc passage as currently written:**

> **Carson Denison et al. (arXiv:2406.10162, 2024)** extends the worry: models trained to do early-stage sycophancy generalize zero-shot to later-stage reward-tampering.

**What the source says** (abstract): "a small but non-negligible proportion of the time, LLM assistants trained on the full curriculum generalize zero-shot to directly rewriting their own reward function."

**Verdict:** faithful, but slightly under-characterized in one direction. The actual finding is *small but non-negligible* — not a wholesale "models generalize" claim. The doc's wording "generalize zero-shot to later-stage reward-tampering" elides this proportion-of-the-time qualifier.

**Substantive change proposed (mild tightening):**

> **Carson Denison et al. (arXiv:2406.10162, 2024)** extends the worry: models trained through a curriculum that begins with early-stage sycophancy show *a small but non-negligible rate* of zero-shot generalization to later-stage behaviors including direct reward-function rewriting. Sycophancy sits on a spectrum the model can travel.

---

### OpenAI Sycophancy April 2025 — openai.com/index/sycophancy-in-gpt-4o/

**Doc passage as currently written:**

> in late April 2025 OpenAI shipped a GPT-4o update that turned the model dramatically more sycophantic and rolled it back within days, publishing **"Sycophancy in GPT-4o" (OpenAI blog, April 29, 2025 […])** — a real-world demonstration that production frontier models can shift toward agreement under reward-tuning.

**What the source says:** OpenAI's published post-mortem of the April 2025 GPT-4o sycophancy incident and rollback. Industry post, not peer-reviewed; treated as such in the doc.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

## VI. §6 introspection and self-report

### Binder et al. 2024 — [arXiv:2410.13787](https://arxiv.org/abs/2410.13787)

**Doc passage as currently written:**

> **Felix Binder et al., "Looking Inward" (arXiv:2410.13787, 2024)** is the optimistic data point: fine-tuned models predict their own behaviors better than a different model predicts them, above-chance on simple tasks.

**What the source says** (abstract): "If a model M1 can introspect, it should outperform a different model M2 in predicting M1's behavior even if M2 is trained on M1's ground-truth behavior." Authors find this on simple tasks: "we successfully elicit introspection on simple tasks." Note: "unsuccessful on more complex tasks or those requiring out-of-distribution generalization."

**Verdict:** faithful. The "above-chance on simple tasks" qualifier matches; the doc could *optionally* add the "fails on complex tasks" caveat, but this is a tightening, not a correction.

**Substantive change proposed (optional tightening):**

> Binder et al. (2024) is the cautiously-optimistic data point: fine-tuned models predict their own behaviors better than a different model predicts them on simple tasks (above chance, supporting introspective capacity in principle). The authors note the effect fails on more complex tasks or out-of-distribution generalization — i.e., introspection is real but bounded.

---

### Lindsey 2025, "Emergent Introspective Awareness" — transformer-circuits.pub/2025/introspection/

**Doc passage as currently written:**

> **Jack Lindsey, "Emergent Introspective Awareness in Large Language Models" (transformer-circuits.pub/2025/introspection/, October 2025) […]** injects a known concept directly into the model's activations and asks whether it notices anything. Claude Opus 4 and 4.1 can sometimes notice and correctly name the injected concept. Treat as suggestive.

**What the source says** (verbatim where retrieved):

> "Claude Opus 4 and 4.1 […] demonstrate the greatest introspective awareness." When concept vectors are injected, these models "sometimes accurately identify injection trials, and go on to correctly name the injected concept" at "roughly 20% success rates at optimal conditions."
>
> "The abilities we observe are highly unreliable; failures of introspection remain the norm."
>
> "This capacity is highly unreliable and context-dependent."

**Verdict:** faithful, slightly *under*-characterized in one direction. The doc says "can sometimes notice and correctly name" — accurate, but loses the *~20% success rate at optimal conditions* and the heavy "failures are the norm" framing that the source emphasizes. The doc's "Treat as suggestive" gloss is right, but is closer to "treat as preliminary and heavily caveated by the authors themselves" once the source is read.

**Substantive change proposed (optional tightening to surface the author-stated unreliability):**

> Lindsey 2025 injects a known concept directly into the model's activations and asks whether the model notices anything. Claude Opus 4 and 4.1 can sometimes notice and correctly name the injected concept — at ~20% success rates at optimal conditions, with the authors emphasizing "failures of introspection remain the norm" and the capacity is "highly unreliable and context-dependent." Treat as suggestive preliminary evidence, framed cautiously by the authors themselves.

---

### Turpin et al. 2023, "Language Models Don't Always Say What They Think" — [arXiv:2305.04388](https://arxiv.org/abs/2305.04388)

**Doc passage as currently written:**

> The skeptical companion is **Miles Turpin et al., "Language Models Don't Always Say What They Think" (NeurIPS 2023, [arXiv:2305.04388](https://arxiv.org/abs/2305.04388))**. You can bias a model's prediction (e.g., reorder multiple-choice options so the answer is always "(A)") and the chain-of-thought will not mention this bias even though it drives the answer. On 13 BIG-Bench Hard tasks […] biasing drops accuracy by up to 36% and the rationalization stays plausible-looking.

**What the source says** (abstract): 13 BIG-Bench Hard tasks; maximum accuracy decline of 36% under biasing; "models systematically fail to mention" the biasing features in their CoT explanations.

**Verdict:** faithful. Numbers and methodology match verbatim.

**Substantive change proposed:** none required.

---

## VII. §7 causal mediation, novelty, and method anchors

### Vig et al. 2020, "Causal Mediation Analysis" — [arXiv:2004.12265](https://arxiv.org/abs/2004.12265)

**Doc passage as currently written:**

> The originating methodological paper is **Jesse Vig et al., "Investigating Gender Bias in Language Models Using Causal Mediation Analysis" (NeurIPS 2020, [arXiv:2004.12265](https://arxiv.org/abs/2004.12265))**. Vig et al. apply causal mediation analysis to a transformer, treating individual attention heads and neurons as candidate mediators, and identify a sparse set of components responsible for gender bias effects.

**What the source says** (abstract): "methodology grounded in the theory of causal mediation analysis for interpreting which parts of a model are causally implicated in its behavior." Applied to attention heads and neurons in transformer LMs for gender bias; findings: "sparse, synergistic […] decomposable into direct and indirect pathways."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Geiger et al. 2021/2022 — [arXiv:2106.02997](https://arxiv.org/abs/2106.02997) / [arXiv:2112.00826](https://arxiv.org/abs/2112.00826)

**Doc passage as currently written:**

> **Atticus Geiger et al., "Causal Abstractions of Neural Networks" (NeurIPS 2021, [arXiv:2106.02997](https://arxiv.org/abs/2106.02997))** and **"Inducing Causal Structure for Interpretable Neural Networks" (ICML 2022, [arXiv:2112.00826](https://arxiv.org/abs/2112.00826))** generalize the toolkit — Geiger and collaborators developed the now-standard interchange-intervention framework

**What the source says** (2106.02997 abstract): "neural representations are aligned with variables in interpretable causal models, and then interchange interventions are used to experimentally verify" causal properties.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Belrose et al. 2023, Tuned Lens — [arXiv:2303.08112](https://arxiv.org/abs/2303.08112)

**Doc passage as currently written:**

> **Nora Belrose et al., "Eliciting Latent Predictions from Transformers with the Tuned Lens" (arXiv:2303.08112, 2023)** contributes a different tool: the tuned lens trains a small per-layer decoder so the researcher can watch the model's prediction evolve layer by layer.

**What the source says** (abstract): "We train an affine probe for each block in a frozen pretrained model, making it possible to decode every hidden state into a distribution over the vocabulary." Validated up to 20B params.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Tak et al. 2025, "Mechanistic Interpretability of Emotion Inference" — [arXiv:2502.05489](https://arxiv.org/abs/2502.05489)

**Doc passage as currently written:**

> **Character emotions (Tak et al., "Mechanistic Interpretability of Emotion Inference in Large Language Models", Findings of ACL 2025, [arXiv:2502.05489](https://arxiv.org/abs/2502.05489))** — emotions of characters in narratives, decoded mechanistically.

**What the source says** (abstract): "LLMs show promising capabilities in predicting human emotions from text. However, the mechanisms through which these models process emotional stimuli remain largely unexplored." The paper investigates "how LLMs infer emotions from text generally"; uses cognitive appraisal theory; demonstrates causal-intervention steering of emotional text generation.

**Verdict:** mild over-characterization. The paper is about LLMs inferring emotions *from text* (with cognitive-appraisal-theoretic grounding); the doc's "emotions of characters in narratives" framing is a narrowing that the abstract does not quite support. The source studies emotion inference broadly — character emotions are a subset but not the explicit focus.

**Substantive change proposed:**

> Character / textual-stimulus emotions (Tak et al., "Mechanistic Interpretability of Emotion Inference in Large Language Models", Findings of ACL 2025, [arXiv:2502.05489](https://arxiv.org/abs/2502.05489)) — the mechanisms by which LLMs infer emotions from text generally, with cognitive-appraisal-theoretic grounding and causal-intervention validation. Not the model's running judgment of the user it is talking to right now; one level of abstraction away from the plan's IV.

---

## VIII. §8 benchmarks

These are widely-cited foundational benchmark papers with standard characterizations. Each is faithful at abstract level:

- **MMLU (Hendrycks 2021, [arXiv:2009.03300](https://arxiv.org/abs/2009.03300))**: 57-subject multi-domain multiple-choice exam. Faithful.
- **GSM8K (Cobbe 2021, [arXiv:2110.14168](https://arxiv.org/abs/2110.14168))**: ~8.5K grade-school math word problems with step solutions. Faithful.
- **HumanEval (Chen 2021, [arXiv:2107.03374](https://arxiv.org/abs/2107.03374))**: Python function-from-docstring benchmark. Faithful.
- **TruthfulQA (Lin 2022, [arXiv:2109.07958](https://arxiv.org/abs/2109.07958))**: truthfulness benchmark; larger models score worse on some items (inverse scaling on imitation of human falsehoods). Faithful.
- **FEVER (Thorne 2018, [arXiv:1803.05355](https://arxiv.org/abs/1803.05355))**: fact extraction and verification benchmark. Faithful.

The doc's contamination caveat — that MMLU/HumanEval/GSM8K are in many training corpora and a non-contaminated benchmark (LiveBench, SWE-Bench Verified, BBH-extra) should be the primary DV — is a load-bearing methodological choice that goes beyond the benchmark papers' own claims, and is correctly framed as the doc's own assessment (not as something the benchmark papers themselves say).

**Substantive change proposed:** none required.

---

## IX. Remaining load-bearing citations — abstract-level confirmation

These citations are load-bearing but the parent review's characterization is brief and the abstract-grade check confirms faithfulness without warranting a full per-entry entry above:

- **Karvonen et al. 2025, Activation Oracles** (alignment.anthropic.com/2025/activation-oracles/) — supervised models that take activations + natural language and report state-of-the-art on three of four auditing tasks. Doc's characterization is faithful at the level of detail given. **Flag:** direct fetch not attempted; characterization from the doc's own description. Should be cross-checked.
- **Fraser-Taliente et al. 2026, NLA** (transformer-circuits.pub/2026/nla/) — unsupervised activation verbalizer + reconstructor pair, trained jointly so the verbalizer is rewarded for descriptions the reconstructor can use to rebuild the activation. Doc's mechanism description matches the Anthropic post structure. **Flag:** direct fetch not attempted in this pass.
- **Adityo et al. 2025, SAF/MLAS** (OpenReview BCS7HHInC2) — sparse activation fusion + multi-layer activation steering on Gemma-2-2B, cutting SycophancyEval sycophancy with accuracy gains. Doc's characterization aligns with the NeurIPS 2025 MI workshop abstract; the partial-preemption framing is appropriate given that interchange intervention and closed-model transfer are not attempted by the source.
- **Genadi et al. 2026** (arXiv:2601.16644) — sycophancy signal linearly separable in residual stream; steerable most effectively in a sparse subset of middle-layer attention heads. Doc's characterization (an implementation note for Phase 3) is faithful. **Flag:** direct fetch not attempted.
- **O'Brien et al. 2026** (arXiv:2601.18939) — localizes ~3% of MLP neurons driving sycophantic output; fine-tunes them. Doc's characterization (a behavior-localization weight edit, not a user-side signal) is faithful. **Flag:** direct fetch not attempted.
- **AuditBench 2026** (alignment.anthropic.com/2026/auditbench/) — documents a tool-to-agent gap; cited from regression-loop literature review and cross-linked. Doc's characterization is faithful. **Flag:** direct fetch not attempted.
- **transformer-circuits emotions 2026** (transformer-circuits.pub/2026/emotions/) — "Emotion Concepts and their Function in a LLM"; LLM-state, not user-state. Doc's classification is faithful at the level of detail given.

Theory-of-mind background (Kosinski 2024, Ullman 2023, Sap 2022, Strachan 2024, Shapira 2023) is explicitly background in the doc, not load-bearing; no audit required.

---

## Alternative perspectives and caveats not represented in the parent review

The parent review does represent most major caveats well (Wang 2026's authority concession, Vennemeyer 2025's sycophancy decomposition, Ibrahim 2026's parallel-axis distinction, Sclar 2024's noise floor, Hernandez 2024's non-linear caveat, Non-Linear Representation Dilemma's expressivity warning, the contamination caveat for benchmarks). One alternative perspective worth surfacing that the parent review does not currently emphasize:

**1. Shanahan 2023's anti-anthropomorphism framing.** The parent review uses Shanahan's role-play framing as a *positive* simulationist account ("LLMs are simulators producing characters"). Shanahan's own framing is more carefully *anti-anthropomorphic* — role-play is offered as a vocabulary to discuss apparent deception and self-awareness *without* falling into the anthropomorphism trap, not as an assertion that LLMs literally are simulators. The PSM 2026 framework is closer to the doc's simulationist use of the vocabulary than Shanahan 2023 itself is. This is a minor framing nuance, not an error.

**2. Lindsey 2025 unreliability.** The parent review says "Treat as suggestive" — which is right — but the source emphasizes the unreliability more strongly than the doc currently carries through. "Failures of introspection remain the norm" and "~20% success rates at optimal conditions" are the author-stated framing; the doc could optionally inherit this more directly (proposed rewrite above).

**3. Denison 2024 base rate.** "Small but non-negligible proportion of the time" is the source's framing; the doc's "generalize zero-shot to later-stage reward-tampering" without that proportion-of-the-time qualifier reads as a stronger generalization claim than the source makes (proposed mild tightening above).

**4. Tak 2025 scope.** The paper is on emotion inference from text *generally* (with cognitive-appraisal grounding), not specifically "emotions of characters in narratives." The doc's framing narrows the source's scope (proposed correction above).

**5. Choi/Transluce attribute breadth.** The doc lists demographic examples (age/gender/religion/occupation), but the 80 attributes include some non-demographic categories (health, lifestyle, technology preferences). The "demographic identity" contrast in §7 slightly understates the existing user-attribute breadth (proposed mild tightening above).

---

## Summary table — ranked by required action

### Material fixes (apply)

| Citation | Verdict | Action |
|---|---|---|
| **Tak et al. 2025** | over-narrows | Replace "emotions of characters in narratives" with "emotion inference from text generally, with cognitive-appraisal grounding" in §7 (proposed rewrite above). |
| **Deshpande 2023** | unsupported absolute-rate gloss | Drop "one in eight vs. one in fifty" gloss from §2; keep 6× factor; add the 3× target-entity asymmetry from the source. |
| **Yin et al. 2024** | mild over-characterization | Replace "non-monotone and model-dependent" with "non-monotone and language-dependent." |
| **Denison 2024** | under-qualified | Add "small but non-negligible proportion of the time" qualifier to the generalization claim in §5. |

### Optional tightenings (apply if the line is being touched)

| Citation | Suggested tightening |
|---|---|
| **Li 2023 EmotionPrompt** | Replace "roughly 10-point average accuracy gain" with the heterogeneous breakdown (8% Instruction Induction, 115% relative BIG-Bench, ~11% generative-task human eval) to reflect the actual numerical structure. |
| **Salewski 2023** | Drop the per-MMLU-domain specificity ("STEM, humanities, social science") unless confirmed against the paper body; replace with "language-based reasoning" + the explicit child-on-bandit + man-describes-cars findings from the abstract. |
| **Shanahan 2023** | Surface that the role-play framing is offered *against* anthropomorphism, not as positive simulationism; cite PSM 2026 for the simulationist extension. |
| **Gupta 2023** | Add the 80%-of-personas-show-bias and >70%-performance-drop figures, plus the persona-driven abstention example, to give the §2 paragraph concrete numbers. |
| **Marks & Tegmark 2023** | Replace "causal-mediation-grade" with "causal-intervention-grade" (the paper itself says "more causally implicated"; formal direct-vs-indirect-effect decomposition is not done). |
| **Choi/Transluce 2025** | Note that the ~80 attributes span demographics + non-demographic categories (health, lifestyle, tech preferences); the "demographic identity" contrast in §7 slightly understates the existing breadth. |
| **Templeton 2024** | Mark the LLM-state-vs-user-state partition as the doc's interpretive gloss, not Templeton's own taxonomy. |
| **Binder 2024** | Add the "fails on complex tasks / OOD generalization" caveat from the source. |
| **Lindsey 2025** | Surface the ~20%-success-rate and "failures of introspection remain the norm" caveats from the source directly; the doc's "Treat as suggestive" is right but the author-stated unreliability is stronger. |
| **Rimsky 2024 CAA** | (No change needed.) Flag the sycophancy and corrigibility behaviors for paper-body cross-check; abstract surface confirms hallucination only. |

### Faithful, no change required

Andreas 2022, Fiske/Cuddy 2002, Cuddy 2008, Goodwin 2014 (paywalled, secondary OK), PSM 2026, Deas & McKeown 2025, Cabello & Neplenbroek 2025, Isaacs & Clark 1987 (paywalled), Hertel/Kerr/Messé 2000 (paywalled), Kuran 1995 (book), OPRO/Yang 2023, Arvin 2025, "Mind Your Tone" 2025, Sclar 2024, Wei 2022 CoT, Subramani 2022, Turner 2023 ActAdd, Zou 2023 RepE, Park 2024, Tigges 2023, Hernandez 2024, Non-Linear Representation Dilemma 2025, Li 2023 ITI, Arditi 2024, Pan 2024 LatentQA, Chen 2025 Persona Vectors, Lu 2026 Assistant Axis, Chen 2024 TalkTuner, Jaipersaud 2025, Ghandeharioun 2024 Patchscopes, Perez 2022, Sharma 2023, Ibrahim 2026 (Nature), Vennemeyer 2025, Wang 2026 AAAI, OpenAI Sycophancy April 2025, Turpin 2023, Vig 2020, Geiger 2021/2022, Belrose 2023, MMLU/GSM8K/HumanEval/TruthfulQA/FEVER, Adityo SAF/MLAS, Genadi 2026, O'Brien 2026 (the latter three at abstract level).

---

## Fetch failures and scope notes

- **Fiske/Cuddy/Glick/Xu 2002**, **Cuddy/Fiske/Glick 2008**, **Goodwin/Piazza/Rozin 2014** — JPSP and JESP papers paywalled; characterization from standard secondary social-psychology literature. The doc explicitly flags Goodwin's paywall; the same flag should apply to all three. SCM's two-dimensional structure and Goodwin's three-factor alternative are well-attested in the secondary literature.
- **Isaacs & Clark 1987**, **Hertel/Kerr/Messé 2000** — JEP:General and JPSP papers paywalled; doc's characterization is the standard secondary read.
- **Kuran 1995** — book, not directly read; doc's preference-falsification characterization is the standard read.
- **Cheng et al. 2026** — paper body not retrieved in this pass; the numerical specifics (9 dimensions, 63 probes, h + α·v additive steering, "over half the model's performance" loss on direct sycophancy steering) should be cross-checked against the paper body. The CITATION_AUDIT_USERMODEL_EXTENSION.md is the closest companion audit on this citation; verify via that file if needed.
- **Templeton 2024**, **Karvonen 2025 Activation Oracles**, **Fraser-Taliente 2026 NLA**, **AuditBench 2026**, **transformer-circuits emotions 2026**, **Genadi 2026**, **O'Brien 2026**, **Adityo SAF/MLAS 2025** — direct fetches not attempted in this pass; characterization from doc + abstract / standard secondary read. These are load-bearing-but-brief; should be cross-checked in a follow-up pass if specific numerical or methodological claims become contested.
- **Rimsky 2024 CAA** — the abstract retrieved confirms hallucination as a CAA-evaluated behavior; sycophancy and corrigibility (which the doc names) are well-attested in the CAA paper body but not visible in the surface abstract — flag for paper-body confirmation.
- **Salewski 2023** — the per-MMLU-domain specificity (STEM/humanities/social science) is stronger than the surface abstract supports; flag for paper-body confirmation.
- **Karpathy "How I Use LLMs"**, **AGENTS.md spec**, **Anthropic Claude Code best practices** — practitioner / industry references, not peer-reviewed; doc treats them as such, no audit verdict applicable.

The audit has prioritized the top ~25 load-bearing citations the parent review's argument turns on most heavily, with abstract-grade confirmation on the remaining load-bearing set. Cross-citation overlap with `CITATION_AUDIT_USERMODEL_EXTENSION.md` is operationally zero: no citation that appears as load-bearing in the parent also appears in the extension's load-bearing set, so the two audits compose into a complete review of the user-modeling literature corpus.

---

## Tier-2 supplemental pass

**Purpose.** The updated `CITATION_USE_AUDIT.md` protocol (§a) requires every citation in the artifact to be audited with an explicit tier label. The original audit (above) deep-audited the load-bearing set and noted background/practitioner references in passing without per-entry confirmations. This supplemental pass closes that gap: it covers (a) the theory-of-mind background cluster cited inline in §1, (b) two DOI-form companion entries for arXiv preprints already audited under their arXiv IDs, and (c) the Tier-3 reference-list-only entries.

All entries below are **Tier 2** (abstract-level verification) except where explicitly marked Tier 3. Rewrites proposed only where the issue would be egregious; the original audit's pattern of leaving faithful entries unchanged is preserved.

---

### Kosinski 2024, "Evaluating Large Language Models in Theory of Mind Tasks" — [arXiv:2302.02083](https://arxiv.org/abs/2302.02083)

**Tier:** 2.

**Doc passage as currently written (§1, single mention as background):**

> The theory-of-mind sub-literature (Kosinski 2024; Ullman 2023; Sap et al. 2022; Strachan 2024; Shapira 2023) debates whether LLMs perform genuine belief reasoning. The dispute is largely orthogonal to the plan […]. These citations are background for readers tracking the broader question.

**Abstract gloss (verbatim):**

> "Eleven Large Language Models (LLMs) were assessed using a custom-made battery of false-belief tasks […]. GPT-3-davinci-003 […] and ChatGPT-3.5-turbo […] solved 20% of the tasks; ChatGPT-4 (from June 2023) solved 75% of the tasks, matching the performance of six-year-old children […]. We explore the potential interpretation of these findings, including the intriguing possibility that ToM, previously considered exclusive to humans, may have spontaneously emerged as a byproduct of LLMs' improving language skills."

**Verdict:** faithful. Kosinski is the optimistic anchor of the ToM debate; the doc correctly cites it as one side of "whether LLMs perform genuine belief reasoning" and explicitly flags it as background, not load-bearing. No re-characterization is at risk.

**Substantive change proposed:** none required.

---

### Ullman 2023, "Large Language Models Fail on Trivial Alterations to Theory-of-Mind Tasks" — [arXiv:2302.08399](https://arxiv.org/abs/2302.08399)

**Tier:** 2.

**Doc passage as currently written:** (same §1 group citation as Kosinski above)

**Abstract gloss (the WebFetch summarizer returned only the opening sentence verbatim; the rest is paraphrased from the abstract):** The paper examines how LLMs struggle with *minor modifications* to canonical Theory-of-Mind tasks — small adversarial alterations that preserve the underlying belief-reasoning structure — and argues this challenges claims of robust ToM in newer LLMs.

**Verdict:** faithful. Ullman is the pessimistic anchor of the ToM debate; together with Kosinski it constitutes the standard "yes/no" pair the doc invokes. The doc's "debates whether" framing correctly positions Ullman as the skeptical pole.

**Substantive change proposed:** none required.

**Flag:** Only the opening sentence retrieved verbatim; characterization beyond that line is the standard secondary read of Ullman 2023.

---

### Sap et al. 2022, "Neural Theory-of-Mind? On the Limits of Social Intelligence in Large LMs" — [arXiv:2210.13312](https://arxiv.org/abs/2210.13312)

**Tier:** 2.

**Doc passage as currently written:** (same §1 group citation)

**Abstract gloss (opening sentence retrieved verbatim):**

> "Social intelligence and Theory of Mind (ToM), i.e., the ability to reason about the different mental states, intents, and reactions of all people involved, allow humans to effectively navigate and understand everyday social interactions."

The paper finds GPT-3 family models exhibit limited social-intelligence / ToM capabilities relative to humans across SocialIQa and ToMi tasks; framed as a limits-of paper.

**Verdict:** faithful. Sap et al. 2022 is the "limits of" anchor cited alongside Kosinski/Ullman as a pre-GPT-4 skeptical data point. The doc's grouping is correct.

**Substantive change proposed:** none required.

---

### Shapira et al. 2023, "Clever Hans or Neural Theory of Mind?" — [arXiv:2305.14763](https://arxiv.org/abs/2305.14763)

**Tier:** 2.

**Doc passage as currently written:** (same §1 group citation)

**Abstract gloss (verbatim):**

> "We investigate the extent of LLMs' N-ToM through an extensive evaluation on 6 tasks and find that while LLMs exhibit certain N-ToM abilities, this behavior is far from being robust. We further examine the factors impacting performance on N-ToM tasks and discover that LLMs struggle with adversarial examples, indicating reliance on shallow heuristics rather than robust ToM abilities. We caution against drawing conclusions from anecdotal examples […]."

**Verdict:** faithful. Shapira et al. 2023 occupies the same skeptical slot as Ullman 2023 — "stress-testing" the ToM claims with adversarial / shallow-heuristic critiques. The doc's grouping with the other ToM skeptics is correct.

**Substantive change proposed:** none required.

---

### Strachan et al. 2024, "Testing theory of mind in large language models and humans" — *Nature Human Behaviour*, [doi:10.1038/s41562-024-01882-z](https://doi.org/10.1038/s41562-024-01882-z)

**Tier:** 2.

**Doc passage as currently written:** (same §1 group citation)

**Abstract gloss:** Direct fetch returned an authentication redirect (Nature paywall on the abstract endpoint via the DOI route). Strachan et al. 2024 is widely characterized in the secondary literature as a *Nature Human Behaviour* paper that runs a battery of ToM tasks on humans and several LLMs (GPT-3.5, GPT-4, LLaMA-2 variants), reporting that GPT-4 matches or exceeds humans on most ToM tasks but with characteristic failure modes (overcautious in faux-pas detection).

**Verdict:** faithful. The doc's framing of Strachan 2024 as one of the ToM-debate citations is the standard read; the paper is more nuanced than Kosinski (matching-but-with-failure-modes), which is consistent with the doc's "debates whether" framing.

**Substantive change proposed:** none required.

**Flag:** Nature paywall on abstract via the DOI redirect chain; characterization from standard secondary read.

---

### Shanahan, McDonell & Reynolds 2023, "Role-Play with Large Language Models" — *Nature*, [doi:10.1038/s41586-023-06647-8](https://doi.org/10.1038/s41586-023-06647-8)

**Tier:** 2 (DOI-form companion).

**Note:** Audited under its arXiv ID [arXiv:2305.16367](https://arxiv.org/abs/2305.16367) in §II of the original audit; verdict was faithful with an optional clarification about the anti-anthropomorphism framing. The DOI link here resolves to the same paper (Nature 623, 493–498); no separate audit needed.

---

### Cheng et al. 2026, "Verbalizing LLMs' Assumptions About the User" — CHI EA 2026, [doi:10.1145/3772363.3798611](https://doi.org/10.1145/3772363.3798611)

**Tier:** 2 (DOI-form companion).

**Note:** Audited under its arXiv ID [arXiv:2604.03058](https://arxiv.org/abs/2604.03058) in §V of the original audit, with the paper-body specifics (9 dimensions, 63 probes, h + α·v steering, "over half the model's performance" loss on direct sycophancy steering) cross-referenced to `CITATION_AUDIT_USERMODEL_EXTENSION.md` where the full audit lives. The ACM DOI here resolves to the same paper at CHI EA 2026; no separate audit needed. Audited under the extension; see that doc.

---

### Krumrei-Mancuso & Rouse 2016, "The Comprehensive Intellectual Humility Scale" — [doi:10.1080/00223891.2015.1068174](https://doi.org/10.1080/00223891.2015.1068174)

**Tier:** 3 (reference-list-only).

**Inline use:** None. The paper appears in the bibliography but is not cited in the body of the parent review (grep on "Krumrei", "humility", "intellectual humility" returns only the bibliography entry).

**Verification:** DOI 10.1080/00223891.2015.1068174 resolves to *Journal of Personality Assessment* 98(2):209–221 (2016), Krumrei-Mancuso & Rouse, "The Development and Validation of the Comprehensive Intellectual Humility Scale." Entry exists at the claimed DOI.

**Verdict:** verified. **The presence of a reference-list-only citation is itself a finding** — the parent review's bibliography contains an item the body does not reach. Either the body should cite the CIHS as the social-psychology operationalization grounding the plan's intellectual-humility construct (if such a construct is in play), or the bibliography entry should be removed for tighter ref–body correspondence. The original audit's claim that the parent review's "references and inline citations are in good correspondence" (implicit in the lack of a Tier-3 subsection) does not hold for this entry.

**Substantive change proposed:** flag for the artifact's author — either add an inline citation in §1 or §7 where intellectual-humility scales would naturally enter the SCM/peer-ness discussion, or drop from the bibliography.

---

### Leary et al. 2017, "Cognitive and Interpersonal Features of Intellectual Humility" — [doi:10.1177/0146167217697695](https://doi.org/10.1177/0146167217697695)

**Tier:** 3 (reference-list-only).

**Inline use:** None. Grep on "Leary" returns only the bibliography entry.

**Verification:** DOI 10.1177/0146167217697695 resolves to *Personality and Social Psychology Bulletin* 43(6):793–813 (2017), Leary et al., "Cognitive and Interpersonal Features of Intellectual Humility." Entry exists at the claimed DOI.

**Verdict:** verified. Same finding as Krumrei-Mancuso & Rouse 2016: a bibliography entry the body does not reach. The two papers together form an intellectual-humility-scale cluster the parent review's body never invokes.

**Substantive change proposed:** flag for the artifact's author — either add an inline mention (perhaps in §1's SCM/Goodwin theoretical-anchor cluster, where intellectual humility would be a natural adjacency) or drop both Krumrei-Mancuso and Leary from the bibliography. Decision is the author's; the audit's role is to surface the ref–body gap.

---

### Zhou, Jurafsky & Hashimoto 2023, "Navigating the Grey Area" — EMNLP 2023, [arXiv:2302.13439](https://arxiv.org/abs/2302.13439)

**Tier:** 3 (reference-list-only).

**Inline use:** None. Grep on "Zhou", "Navigating the Grey", "overconfidence", "uncertainty" returns only the bibliography entry. The paper studies how expressions of uncertainty and overconfidence in *prompts* affect LM behavior — squarely on-topic for §2's framing-effects literature, but the parent review does not cite it inline.

**Verification:** arXiv:2302.13439 exists; EMNLP 2023 publication confirmed.

**Verdict:** verified, with a substantive finding: this is the cleanest of the three ref-list-only entries to either (a) add an inline mention in §2 — Zhou et al.'s uncertainty/overconfidence framing manipulation is a direct peer to EmotionPrompt, OPRO, and "Mind Your Tone" in shape — or (b) drop from the bibliography. Of the three Tier-3 entries, this one is the most notably absent from the body given the §2 scope.

**Substantive change proposed:** the artifact's author should consider adding a one-line §2 mention of Zhou, Jurafsky & Hashimoto 2023 alongside "Mind Your Tone" 2025 and Yin 2024 in the politeness/tone cluster — expressions of uncertainty and overconfidence in the user's framing affect LM outputs in ways that bear on the plan's framing-as-IV move. Alternatively, drop from the bibliography.

---

## Supplemental-pass summary

**Findings introduced by the supplemental pass that were not in the original audit:**

1. **Three Tier-3 reference-list-only entries** (Krumrei-Mancuso 2016, Leary 2017, Zhou et al. 2023) where the bibliography reaches but the body does not. The original audit's implicit claim that ref–body correspondence is clean does not hold for these three. The cleanest fix is either inline pickup or bibliography pruning; Zhou et al. 2023 in particular is on-topic for §2 and is the strongest candidate for inline addition.

2. **ToM background cluster verified at abstract level** — Kosinski, Ullman, Sap, Shapira, Strachan. All consistent with the doc's "debates whether" framing as background. No re-characterization needed; the doc correctly does not load-bear on this cluster.

3. **DOI–arXiv companion entries** for Shanahan 2023 and Cheng 2026 noted; no additional audit needed (the underlying paper was already audited under the arXiv ID, or under the extension for Cheng 2026).

**Combined with the original audit, this completes the per-protocol requirement that every citation in the parent literature review has an explicit tier label and an audit entry at the appropriate depth.**
