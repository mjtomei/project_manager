# Citation Audit — Cycle 11 Precursor A

**Scope:** full-text reads (not just abstracts) of the entropy / decoding / ventriloquizing cluster cited in `pm/docs/literature-review-user-model-extension.md` §§2.2, 3.4, 4.3, 4.4.

**Method:** arXiv HTML and PDF extraction via `pdftotext`; verbatim quotes where retrievable, paraphrase with section reference otherwise. Fetch failures flagged in place.

---

### Holtzman et al. 2020, "The Curious Case of Neural Text Degeneration" — arXiv:1904.09751

**Doc passage as currently written:**
> The historical evidence — Holtzman et al. 2020's neural-text-degeneration — captures the *crude* form: greedy decoding collapses into surface-repetitive loops on older models. Modern models have substantially solved that surface failure.

**What the source actually says** (abstract + standard secondary read; full-text fetch returned only abstract):
> "[U]sing likelihood as a decoding objective leads to text that is bland and strangely repetitive." The paper introduces **nucleus (top-p) sampling**, "sampling text from the dynamic nucleus of the probability distribution, which allows for diversity while effectively truncating the less reliable tail." The headline phenomena are repetition loops and probability-mass collapse under greedy/beam decoding on GPT-2 (the paper's primary model). The paper does not claim the failure is universal across all model scales nor that future larger/aligned models will solve it.

**Verdict:** faithful (with one minor caveat — the doc's claim that "modern models have substantially solved that surface failure" is not Holtzman's claim, it is the review's own contemporary assessment, and is presented as such; the attribution to Holtzman is only of the original degeneration documentation).

**Substantive change proposed:** none required. Optional tightening to make the model scope explicit:
> The historical evidence — Holtzman et al. 2020's neural-text-degeneration on GPT-2-class models — captures the *crude* form: greedy/beam decoding collapses into surface-repetitive loops. Modern frontier models have substantially solved that surface failure (this review's assessment, not Holtzman's claim).

---

### Venkatraman et al. 2024, "GPT-who" — arXiv:2310.06202 / NAACL Findings 2024

**Doc passage as currently written (§2.2):**
> AI-text detectors operating on "burstiness" (Venkatraman et al. 2024 / GPT-who; the broader perplexity-variance detection literature, §3.4) already exploit this signature on text that humans cannot reliably distinguish.

**Doc passage as currently written (§3.4):**
> Venkatraman et al. (2024), "GPT-who" — NAACL Findings — UID features distinguish human from machine text; "burstiness" in AI-text detection is essentially the temporal-entropy-structure claim in operational form.

**What the source actually says** (ACL Anthology abstract; full paper not retrievable in this pass):
> Abstract: "[E]mploys UID-based features to model the unique statistical signature of each LLM and human author for accurate detection." Compared against GLTR, GPTZero, DetectGPT, OpenAI detector, ZeroGPT; evaluated on 4 benchmark datasets. The abstract frames the central question as "if [the] UID principle can help capture differences between LLMs-generated and human-generated texts." The abstract does **not** use the word "burstiness" and does not explicitly claim it detects text that humans cannot distinguish.

**Verdict:** over-characterizes on two minor points. (a) "Burstiness" is the term-of-art in a different detector line (e.g., GPTZero) — the doc conflates GPT-who's UID-variance features with the burstiness framing. They are related (both perplexity-variance-flavored), but the conflation is a real slip. (b) The "text that humans cannot reliably distinguish" qualifier is a known property of LLM output that is true of the detection problem GPT-who addresses, but it is not specifically attributed to or measured in GPT-who.

**Substantive change proposed (rewrite for §2.2):**
> AI-text detectors operating on perplexity-variance features (Venkatraman et al. 2024 / GPT-who uses UID-based variance features; the broader "burstiness" detection literature — e.g., GPTZero — uses related per-segment perplexity-variance signals, §3.4) already exploit this signature, on a detection task widely held to be hard for humans.

**Substantive change proposed (rewrite for §3.4):**
> Venkatraman et al. (2024), "GPT-who" — NAACL Findings — UID-derived statistical features distinguish human from machine text across four benchmark datasets, outperforming GLTR, GPTZero, DetectGPT, OpenAI detector, and ZeroGPT. The closest existing operationalization of "exploit the variance/profile of token-level information content for detection." (Burstiness as a term-of-art belongs to a related detector line, not GPT-who specifically.)

---

### Hamilton 2024, "Detecting Mode Collapse in Language Models via Narration" — arXiv:2402.04477

**Doc passage as currently written (§2.2):**
> West et al. (2024, §3.7) provides the most direct empirical buttress: successive aligned GPT-3 versions empirically lose the ability to assume multiple authorial voices — the "ventriloquizing both sides" symptom, observed.

**Doc passage as currently written (§3.7):**
> **West et al. (2024), "Detecting Mode Collapse in Language Models via Narration"** — arXiv:2402.04477. Documents that successive aligned GPT-3 versions lose the ability to assume multiple authorial voices — *the strongest empirical support for §2.2's "one author ventriloquizing both sides" claim*. Diagnosis only.

**What the source actually says** (full text, arXiv:2402.04477v1, 6 Feb 2024):
> **Single author: Sil Hamilton, McGill University.** (The doc's attribution to "West et al." is incorrect.)
> Abstract (verbatim): "By studying 4,374 stories sampled from three OpenAI language models, we show successive versions of GPT-3 suffer from increasing degrees of 'mode collapse' whereby overfitting the model during alignment constrains it from generalizing over authorship: models suffering from mode collapse become unable to assume a multiplicity of perspectives."
> Methodology (verbatim): "We assess authorial conjuration by conducting a topic analysis over all generated stories. Topic analyses are a routine stylometric technique for identifying and clustering lexical regularities in a given corpus."
> Construct measured: *single-author-voice diversity across separate prompts* — the three models (`davinci-instruct-beta`, `text-davinci-003`, `gpt-3.5-turbo`) are each asked to generate stories under varied prompts intended to elicit distinct implied authors; the topic analysis tests whether the resulting stories cluster by intended persona or collapse into a generic voice. The construct is *not* a single-conversation, both-sides ventriloquism measurement.
> Future-work passage (line 411): the paper explicitly notes it has not tested "mode collapse when predicting other textual genres, such as conversations or non-fictional writing" — confirming that dialogue/conversational ventriloquism is *out of scope* of the actual study.

**Verdict:** **mischaracterizes** on two load-bearing points:
1. **Author attribution wrong.** Sole author is Sil Hamilton, not "West et al."
2. **Construct mismatch.** Hamilton measures single-author voice diversity *across distinct prompts*; §2.2's "one author ventriloquizing both sides" is a *within-single-conversation* claim about dialogue. They are *related* (both are mode-collapse-flavored, both implicate alignment-induced flattening) but they are not the same measurement, and the paper explicitly disclaims having tested the conversational case.

**Substantive change proposed (rewrite for §2.2):**
> Hamilton (2024, §3.7) provides partial empirical buttress: across 4,374 stories from three successively-aligned GPT-3 family models (`davinci-instruct-beta` → `text-davinci-003` → `gpt-3.5-turbo`), topic analysis shows the newer aligned models lose the ability to assume distinct implied authors across prompts — a single-author-voice-diversity loss. The "ventriloquizing both sides within one conversation" claim of this review is *adjacent* to but not identical with Hamilton's measurement (the paper explicitly disclaims having tested the conversational genre), so the support is suggestive rather than direct. A dialogue-level replication is open.

**Substantive change proposed (rewrite for §3.7):**
> **Hamilton (2024), "Detecting Mode Collapse in Language Models via Narration"** — arXiv:2402.04477 (sole author: Sil Hamilton, McGill). Documents single-author-voice diversity loss across successive aligned OpenAI GPT-3 family models via topic analysis over 4,374 generated stories. *Closest empirical neighbour* to §2.2's ventriloquism claim, but the measurement is across-prompts single-author rather than within-conversation two-sided — a dialogue replication is an open extension, not work this paper has done. Diagnosis only.

---

### Shumailov et al. 2024, "AI models collapse when trained on recursively generated data" — *Nature* 631:755–759 / arXiv:2305.17493

**Doc passage as currently written (§2.2):**
> Model collapse under recursive training on LLM-generated text (Shumailov et al. 2024, *Nature*; precursor 2023, *The Curse of Recursion*, §3.7) is the same signature seen from the training side: LLM text is missing something present in human text. *(Conjecture by this review, not Shumailov's claim: the missing something is most plausibly the between-perspective entropy contribution; Shumailov attributes collapse to statistical / expressivity / approximation error compounding without specifying its content.)*

**Doc passage as currently written (§3.7):**
> **Shumailov et al. (2024), "AI models collapse when trained on recursively generated data"** — *Nature* 631:755–759. Precursor: "The Curse of Recursion," arXiv:2305.17493. Tails of the distribution disappear under recursive synthetic training.

**What the source actually says** (Nature paywalled; arXiv:2305.17493 full-text via pdftotext):
> The arXiv version's Section 3.1 identifies error sources behind model collapse:
> - **Statistical approximation error** (primary): "arises due to the number of samples being finite, and disappears as the number of samples tends to infinity."
> - **Functional approximation error** (secondary): "stems from our function approximators being insufficiently expressive (or sometimes too expressive outside of the original distribution support)."
> - A third, **functional expressivity error**, appears in the paper's taxonomy and is widely cited in secondary sources but I could not pull the verbatim definition from this extraction pass — flagged.
>
> Core mechanism (verbatim from abstract): "use of model-generated content in training causes irreversible defects in the resulting models, where tails of the original content distribution disappear." Models "converge to a point estimate with very small variance" over generations.
> Tested systems: Gaussian Mixture Models, Variational Autoencoders, and OPT-125M (the language model). Each generation trains on data sampled from the previous generation: "model 1 was trained on the data produced by model 0; model 2 was trained on data produced by model 1."

**Verdict:** **under-characterizes** the source slightly. Shumailov is *more specific than* "abstract error compounding without specifying content" — the paper explicitly says the *tails of the original distribution disappear* and the distribution *converges to a low-variance point estimate*. That is a content claim about what is lost (low-probability events / tails), even if the paper does not name "between-perspective entropy" as the content. The doc's parenthetical conjecture remains a legitimate reinterpretation of *which* tails matter, but the framing that Shumailov "does not specify content" is too strong.

**Substantive change proposed (rewrite for §2.2 parenthetical):**
> *(Conjecture by this review, not Shumailov's claim: the operative missing piece is the between-perspective entropy contribution. Shumailov is more specific than mere error-compounding — the paper identifies the lost content as the **tails of the original distribution** (low-probability events, rare modes), with distributions converging to low-variance point estimates over generations. This review's conjecture refines "what kind of tails" — perspective-distinguishing structure — but does not contradict Shumailov.)*

**Substantive change proposed (rewrite for §3.7):**
> **Shumailov et al. (2024), "AI models collapse when trained on recursively generated data"** — *Nature* 631:755–759 (precursor: arXiv:2305.17493). Recursive training on a model's own outputs causes the tails of the original distribution to disappear and the distribution to converge to a low-variance point estimate. Tested on Gaussian Mixture Models, Variational Autoencoders, and OPT-125M. Section 3.1 attributes the dynamic primarily to **statistical approximation error** (finite-sample tail loss) and secondarily to **functional approximation error** (limited expressivity of approximators).

---

### Arora et al. 2023, "The Stable Entropy Hypothesis and Entropy-Aware Decoding" — arXiv:2302.06784

**Doc passage as currently written (§3.4):**
> **Arora et al. (2023), "The Stable Entropy Hypothesis and Entropy-Aware Decoding"** — arXiv:2302.06784. Claims human-like generation occupies "a narrow and nearly flat" entropy band across models, tasks, and domains; decodes to stay inside. **Caveat (this review, not the paper's):** the paper claims broad generalizability, but the empirical work was built on GPT-2/3-era LMs against degeneration failure modes that current models have substantially solved.

**What the source actually says** (full-text extraction):
> Models actually tested (verbatim from §2.1 and §3.1):
> - Text completion: **GPT-2 XL (1.5B)** and **OPT (1.3B)**
> - Summarization: **BART** and **Pegasus** ("90M and 1B parameters")
> - Dialog: **BlenderBot (1B)**
> - Story generation: WritingPrompts dataset (model unspecified in the excerpts I extracted, but in the same GPT-2/BART era)
>
> Largest LM tested: **GPT-2 XL at 1.5B parameters**. No model in the paper exceeds ~1.5B parameters. No LLaMA, Mistral, Qwen, Gemma, or instruction-tuned modern model is evaluated.

**Verdict:** **faithful** — the review's caveat correctly identifies the model-regime gap. If anything the review *understates* it: the largest LM Arora tested (1.5B) is two-plus orders of magnitude smaller than current frontier LMs, and none of the tested models is instruction-tuned or RLHF-aligned.

**Substantive change proposed (tighter, more specific caveat):**
> **Arora et al. (2023), "The Stable Entropy Hypothesis and Entropy-Aware Decoding"** — arXiv:2302.06784. Claims human-like generation occupies "a narrow and nearly flat" entropy band across models, tasks, and domains; decodes to stay inside. **Models actually tested:** GPT-2 XL (1.5B), OPT (1.3B), BART (90M/1B), Pegasus, BlenderBot (1B) — all pre-LLaMA-era base models, none instruction-tuned, largest at 1.5B parameters. **Caveat (this review, not the paper's):** the "narrow and nearly flat" claim is asserted broadly but the empirical support is exclusively on this small-base-LM regime, against degeneration failure modes that current frontier instruction-tuned LMs have substantially solved. Reproduction on modern LMs is required before transferring the conclusion; §4.3 frames the reproduction question.

---

### Ahmed & Singh 2026, "EPIC: Entropy-Aligned Decoding" — arXiv:2601.01714

**Doc passage as currently written (§3.4):**
> Figure 1 plots the LM's predictive entropy on its own generation against the typical band; the cat-cat-cat panel shows monotonic decay from in-band to ~0 as the repetition entrenches — consistent with Holtzman-style degeneration, not anomalous; the earlier figure-semantics suspicion is retracted. Evaluations include AlpacaEval Creative Writing, CNN/DailyMail summarization, and GSM8K (an engineering-style task). **Caveat (§4.3):** if "The cat" prompt suffices to drive an EPIC-tested model into cat-cat-cat degeneration in the first place, the model class they are correcting against is weaker than current frontier LMs ...

**Doc passage as currently written (§4.3):**
> **Ahmed & Singh 2026 (Epic, §3.4)** — ... AlpacaEval / CNN-DailyMail / GSM8K evaluations are present. **The remaining concern is model-regime:** if EPIC's models degenerate on "The cat," the regime they correct against may be weaker than the LMs §4.3 actually cares about.

**What the source actually says** (full-text extraction of v1):
> Datasets evaluated (§5.2, verbatim): "For story generation, we evaluate on the W RITING P ROMPTS dataset (Fan et al., 2018a). For abstractive summarization, we evalaute on the CNN/DAILY M AIL dataset (Nallapati et al., 2016)." For math reasoning: "the GSM8K dataset (Cobbe et al., 2021b)."
> **Note:** the doc says "AlpacaEval Creative Writing" — but the paper actually uses **WritingPrompts**, not AlpacaEval. AlpacaEval is referenced only in the table of contents / abstract style framing per the secondary read; the evaluation dataset is WritingPrompts. Doc citation needs correction.
> Judge: ChatGPT-5 used as the LM-as-judge for win-rate computation.
> **Base LM:** the paper *does not name* the underlying base LM anywhere I could locate in the main text or experimental sections (`grep` over the full extracted PDF for Llama / Mistral / Qwen / Gemma / GPT-2 / GPT-3 / Pythia / OPT / Phi returns zero substantive hits). The paper only says "We use the HuggingFace framework ... employing their implementations of top-p, top-k, min-p, temperature sampling, and typical decoding." This is a real reproducibility gap in the paper itself.
> Figure 1: an illustrative entropy-trajectory diagram with four panels (typical band, cat-cat-cat degeneration, gibberish, EPIC) conditioned on "The cat" prompt. The caption frames the panels conceptually; the cat-cat-cat panel is presented as illustrative of the degeneration mode the method targets, not as a specific empirical sample tied to a named model. The previous figure-semantics suspicion (that it might be a real EPIC-base-model sample showing pathological behavior) is settled: it appears to be **schematic/illustrative**, not an empirical sample from the EPIC-tested base model.

**Verdict:** mixed — partially faithful, partially over-characterizes:
- **Wrong dataset name:** the doc lists "AlpacaEval Creative Writing" but the actual evaluation dataset is WritingPrompts. Mischaracterization, easily fixed.
- **Figure 1 reading more nuanced than the doc allows:** the cat-cat-cat panel reads as schematic/illustrative rather than a real model output, which actually *strengthens* the §4.3 caveat — we cannot infer the base model's weakness from it because it is not a real sample. The "monotonic decay from in-band to ~0" description is consistent with the figure but should be flagged as describing an illustrative panel, not measured behavior.
- **Base-model identity:** the §4.3 caveat about "if EPIC's models degenerate on 'The cat'..." is *unanswerable* from the paper because the paper does not name its base LM. This is a more serious gap than the doc currently reflects. The right caveat is "the paper does not specify the base LM, so the model-regime question cannot be settled from the paper text alone."

**Substantive change proposed (rewrite for §3.4):**
> **Ahmed & Singh (2026), "EPIC: Entropy-Aligned Decoding"** — arXiv:2601.01714. k-step-lookahead, position-dependent entropy calibration to a "typical" entropy band derived from the data distribution. Figure 1 is a **schematic** four-panel diagram (typical band, cat-cat-cat repetition, gibberish, EPIC) illustrating the regimes the method targets, not an empirical sample tied to a specific model. Evaluations: **WritingPrompts** (creative writing), **CNN/DailyMail** (summarization), **GSM8K** (math reasoning), with ChatGPT-5 as LM-as-judge. **Significant reproducibility gap:** the paper does not name the underlying base LM in its experimental section (searched main text for Llama/Mistral/Qwen/Gemma/GPT-2/GPT-3/Pythia/OPT/Phi — no matches), only stating "We use the HuggingFace framework." The §4.3 reproduction question therefore stands on stronger ground than initially framed: without knowing EPIC's base model we cannot transfer its gains to a known modern model class.

**Substantive change proposed (rewrite for §4.3 bullet):**
> **Ahmed & Singh 2026 (EPIC, §3.4)** — k-step-lookahead position-dependent entropy calibration. Evaluations: WritingPrompts, CNN/DailyMail, GSM8K (not AlpacaEval as previously stated). **The base LM is unspecified in the paper text**, which makes the model-regime question genuinely open: EPIC's gains may or may not transfer to current frontier LMs, and the paper does not give us enough to tell. The §4.3 reproduction-on-named-modern-models question therefore stands.

---

### Entropy-UID 2025 — arXiv:2502.14366

**Doc passage as currently written (§3.4 / §3.7):**
> **Entropy-UID (2025)** — arXiv:2502.14366. Optimizes generation toward lower surprisal and lower entropy variance — the most direct existing instance of "use a UID-derived signal to shape generation," at decoding time.

**What the source actually says** (abstract only; full paper is ~5 pages, ACL 2025 short):
> Method: "adaptive adjustment of token selection by jointly minimizing entropy and surprisal, promoting more even information distribution across generated sequences." Decoding-time. Compared against "standard GPT-2 and alternative heuristics." Evaluated on WikiText-2, OpenWebText, WMT.

**Verdict:** faithful, modulo the same model-regime caveat as Arora — Entropy-UID is evaluated against **GPT-2**, not modern LMs. The doc does not currently flag this.

**Substantive change proposed:**
> **Entropy-UID (2025)** — arXiv:2502.14366. Decoding-time token selection that jointly minimizes entropy and surprisal, optimizing for lower entropy variance across the sequence — the most direct existing instance of "use a UID-derived signal to shape generation." **Evaluated against standard GPT-2** on WikiText-2 / OpenWebText / WMT; modern-LM transfer is open.

---

### ForTIFAI 2025 — arXiv:2509.08972

**Doc passage as currently written (§3.7):**
> **ForTIFAI (2025)** — arXiv:2509.08972. Truncated-Cross-Entropy loss ignores high-confidence tokens (the synthetic fingerprint). Closest existing "detect-what's-missing via entropy signature" intervention — but per-token confidence rather than temporal profile, and defensive (collapse mitigation) rather than generative bootstrap.

**What the source actually says** (abstract only — full-text not fetched):
> Truncated Cross-Entropy (TCE) loss "selectively ignor[es] high-confidence tokens during training, effectively filtering out likely machine-generated artifacts." Motivation: mitigating model collapse on synthetic data. Result: "tolerating over 2.3x more synthetic data before the onset of collapse." The signal operates on per-token confidence, not on a temporal profile or distribution shape. Defensive framing (collapse mitigation), not generative bootstrap.

**Verdict:** faithful. The doc's characterization aligns with the abstract on all three load-bearing points (per-token vs. temporal, defensive vs. generative, "detect-what's-missing via entropy signature" framing).

**Substantive change proposed:** none required. Optionally add the quantitative result for context:
> ... defensive (collapse mitigation) rather than generative bootstrap. Reported gain: 2.3× more synthetic data tolerated before collapse onset.

---

### Meister et al. 2021, "Revisiting the Uniform Information Density Hypothesis" — EMNLP 2021

**Doc passage as currently written (§3.4):**
> Meister et al. (2021), "Revisiting the Uniform Information Density Hypothesis" — UID (Levy & Jaeger 2007) predicts humans *flatten* surprisal — challenges the "rich ebb and flow" premise the §4.3 study must first test.

**What the source actually says** (full-text extraction):
> Findings on the UID hypothesis are *more supportive than* the doc allows. Verbatim from the abstract / intro:
> - "[W]e provide weakly super-linear effect of surprisal, which would be compatible with UID's predictions."
> - "[W]e present evidence that non-uniformity in information [content is dispreferred] ... [there is] regression towards a mean surprisal across the document — a finding that supports a typical interpretation of UID."
> - "[F]or sentence acceptability judgments, we [find] a [super-linear effect] of sentence-level surprisal ... consistent with a preference for UID in language."
>
> The paper is a *Revisiting* — it finds the evidence base is mixed but on balance *supports* UID under a "typical" interpretation, while noting that multiple operationalizations of UID exist and "lack clarity or unity."

**Verdict:** faithful in direction (the paper does support a UID-flattening reading), but the doc's framing as a clean "humans flatten surprisal" challenge is a slight oversimplification. The paper's actual position is more careful: UID is supported under specific operationalizations (mean-surprisal regression, super-linear acceptability cost), and previous evidence base is more ambiguous than typically presented.

**Substantive change proposed:**
> Meister et al. (2021), "Revisiting the Uniform Information Density Hypothesis" — finds a weakly super-linear effect of surprisal on reading time and a super-linear surprisal cost in sentence-acceptability judgments, both compatible with UID; also finds regression toward mean surprisal across documents, supporting a "typical" interpretation of UID as flattening. (The paper notes UID has multiple operationalizations that "lack clarity or unity" — support is interpretation-dependent.) Either way, the finding tension-tests the "rich ebb and flow" premise the §4.3 study must first establish.

---

### Verma et al. 2023, "Revisiting Entropy Rate Constancy in Text" — Findings of EMNLP 2023

**Doc passage as currently written (§3.4):**
> Verma et al. (2023), "Revisiting Entropy Rate Constancy in Text" — fails to replicate on neural LMs; weakens the robust-temporal-signature claim.

**What the source actually says** (full-text extraction):
> Verbatim from the abstract: "We re-evaluate the claims of Genzel and Charniak (2002) with neural language models, failing to find clear evidence in support of entropy rate constancy."
> Setup: measures entropy rate on Penn Treebank, Common Crawl News, NYT Annotated Corpus, and an Arabic Billion Words subset, comparing a smoothed trigram model against **GPT-2 XL (1.5B)**.
> From Figure 1 caption (verbatim): "Genzel and Charniak (2002) showed that entropy rate increased under n-gram models and predicted that it would remain constant in models which can condition on long-range context. We replicate the former result but do not find clear evidence supporting the latter."

**Verdict:** faithful. The doc's one-line summary accurately captures the paper's finding.

**Substantive change proposed:** none required. Optional tightening:
> Verma et al. (2023), "Revisiting Entropy Rate Constancy in Text" — replicates the Genzel & Charniak entropy-rate-increase finding under n-gram models on Penn Treebank, Common Crawl News, NYT, and an Arabic corpus, but with **GPT-2 XL (1.5B)** fails to find evidence for the predicted constancy under long-range neural conditioning. Weakens the robust-temporal-signature claim — though, like Arora and Entropy-UID, the test was on a GPT-2-era model and modern frontier behavior is open.

---

## Summary of load-bearing changes the doc should make

1. **Fix author attribution: "West et al. 2024" → "Hamilton 2024" (sole author Sil Hamilton)** at every occurrence (§2.2, §3.7, §4.4). This is a factual error.
2. **Soften the Hamilton 2024 buttress claim:** the paper measures cross-prompt single-author voice diversity in *stories*, and explicitly disclaims having tested conversational genre. It is an adjacent precedent, not a direct measurement of dialogue ventriloquism.
3. **Fix EPIC dataset name: "AlpacaEval Creative Writing" → "WritingPrompts"** in §3.4 and §4.3.
4. **Strengthen the EPIC base-model caveat:** the paper does not name its base LM. The §4.3 model-regime question is unanswerable from the paper text, which makes the reproduction-on-named-models call *more* warranted, not less. The cat-cat-cat panel of Figure 1 reads as schematic/illustrative, not an empirical model sample, so cannot be used to infer base-model weakness either way.
5. **Refine the Shumailov parenthetical:** Shumailov is more specific than "abstract error compounding" — the paper names tail loss and convergence to low-variance point estimates. The review's between-perspective-entropy refinement is a legitimate reinterpretation but should not contrast with a strawman.
6. **Make model-regime explicit on Arora, Entropy-UID, Verma:** all three were evaluated on GPT-2-XL / OPT-1.3B / BART / Pegasus / BlenderBot class models — none on modern frontier or instruction-tuned LMs. The §4.3 modern-models question applies to all of them uniformly.
7. **Small slip on GPT-who:** "burstiness" is a related-but-distinct detector-line term; GPT-who specifically uses UID-variance features. The doc currently conflates them.

## Fetch failures / scope notes

- **Shumailov *Nature* version** is paywalled (auth redirect). All Shumailov quotes are from the arXiv precursor (2305.17493), which the Nature paper extends but does not contradict on the points audited here.
- **Holtzman, GPT-who, Entropy-UID, ForTIFAI** — full PDFs not retrieved; relied on arXiv / ACL Anthology abstracts plus standard secondary knowledge. Where the verdict turns on a load-bearing claim not in the abstract, this is flagged in the entry.
- **Arora, EPIC, Meister 2021, Verma 2023, Hamilton 2024** — full PDFs extracted via `pdftotext`; verbatim quotes are from those extractions.
- The "third Shumailov error source" (functional expressivity error) is widely cited but I could not pull the verbatim definition from this extraction pass; flagged as a known gap rather than confirmed.
