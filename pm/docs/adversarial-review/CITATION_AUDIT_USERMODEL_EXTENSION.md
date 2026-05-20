# Citation Audit — User-Modeling Literature Review Extension

**Artifact audited:** `pm/docs/literature-review-user-model-extension.md`.

**Scope.** Full-text reads of load-bearing citations across the extension's substantive sections (§§2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.7, 4.1, 4.2, 4.3, 4.4). Run as the Phase 3 detailed audit per `CITATION_USE_AUDIT.md`, before the Cycle 11 adversarial review.

**Method.** arXiv HTML and PDF extraction via `pdftotext`; verbatim quotes where retrievable; secondary sources (e.g., Stanford Encyclopedia of Philosophy) for paywalled books, flagged in place. Audit was parallelized across four thematic chunks (entropy/decoding; branching/test-time compute; bootstrap/self-improvement; philosophy/deception); this file is the merged output for walkthrough.

**How to walk this.** Read top-to-bottom and apply or reject each proposed rewrite. Faithful entries (no change required) carry the verdict "faithful" and can be skimmed. The combined summary table at the end ranks entries by required action.

---

## I. Entropy, decoding, ventriloquizing — §§2.2, 3.4, 4.3, 4.4

### Holtzman et al. 2020, "The Curious Case of Neural Text Degeneration" — [arXiv:1904.09751](https://arxiv.org/abs/1904.09751)

**Doc passage as currently written:**
> The historical evidence — Holtzman et al. 2020's neural-text-degeneration — captures the *crude* form: greedy decoding collapses into surface-repetitive loops on older models. Modern models have substantially solved that surface failure.

**What the source actually says** (abstract + standard secondary read; full-text fetch returned only abstract):
> "[U]sing likelihood as a decoding objective leads to text that is bland and strangely repetitive." The paper introduces **nucleus (top-p) sampling**, "sampling text from the dynamic nucleus of the probability distribution, which allows for diversity while effectively truncating the less reliable tail." The headline phenomena are repetition loops and probability-mass collapse under greedy/beam decoding on GPT-2 (the paper's primary model). The paper does not claim the failure is universal across all model scales nor that future larger/aligned models will solve it.

**Verdict:** faithful (with one minor caveat — the doc's claim that "modern models have substantially solved that surface failure" is not Holtzman's claim, it is the review's own contemporary assessment, and is presented as such; the attribution to Holtzman is only of the original degeneration documentation).

**Substantive change proposed** (optional tightening to make the model scope explicit):
> The historical evidence — Holtzman et al. 2020's neural-text-degeneration on GPT-2-class models — captures the *crude* form: greedy/beam decoding collapses into surface-repetitive loops. Modern frontier models have substantially solved that surface failure (this review's assessment, not Holtzman's claim).

---

### Venkatraman et al. 2024, "GPT-who" — [arXiv:2310.06202](https://arxiv.org/abs/2310.06202) / [NAACL Findings 2024](https://aclanthology.org/2024.findings-naacl.8/)

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

### Hamilton 2024, "Detecting Mode Collapse in Language Models via Narration" — [arXiv:2402.04477](https://arxiv.org/abs/2402.04477)

**Doc passage as currently written (§2.2 — after the in-progress fix to "Hamilton (2024)"):**
> Hamilton (2024, §3.7) provides *suggestive corroboration*: across three successive OpenAI models … become measurably more lexically homogeneous (BERTopic clustering on 4,374 stories) … The measured construct is single-author-diversity-across-prompts rather than within-dialogue voice separation, so this corroborates the §2.2 averaged-perspective direction without directly observing within-conversation ventriloquism.

**Doc passage as currently written (§3.7):**
> Hamilton (2024), "Detecting Mode Collapse in Language Models via Narration" — [arXiv:2402.04477](https://arxiv.org/abs/2402.04477) (EACL 2024 Workshop … sole author …). Across three successive OpenAI models … become measurably more lexically homogeneous … *Suggestive corroboration* for §2.2's averaged-perspective direction …

**What the source actually says** (full text, [arXiv:2402.04477](https://arxiv.org/abs/2402.04477)v1, 6 Feb 2024):
> **Single author: Sil Hamilton, McGill University.**
>
> Abstract (verbatim): "By studying 4,374 stories sampled from three OpenAI language models, we show successive versions of GPT-3 suffer from increasing degrees of 'mode collapse' whereby overfitting the model during alignment constrains it from generalizing over authorship: models suffering from mode collapse become unable to assume a multiplicity of perspectives."
>
> Methodology (verbatim): "We assess authorial conjuration by conducting a topic analysis over all generated stories. Topic analyses are a routine stylometric technique for identifying and clustering lexical regularities in a given corpus."
>
> Construct measured: *single-author-voice diversity across separate prompts* — the three models (`davinci-instruct-beta`, `text-davinci-003`, `gpt-3.5-turbo`) are each asked to generate stories under varied prompts intended to elicit distinct implied authors; the topic analysis tests whether the resulting stories cluster by intended persona or collapse into a generic voice. The construct is *not* a single-conversation, both-sides ventriloquism measurement.
>
> Future-work passage (line 411): the paper explicitly notes it has not tested "mode collapse when predicting other textual genres, such as conversations or non-fictional writing" — confirming that dialogue/conversational ventriloquism is *out of scope* of the actual study.

**Verdict:** the author attribution fix already landed. The construct-mismatch nuance is partially in the current text but could be sharpened — the paper *explicitly disclaims* dialogue testing, which is stronger than the current "rather than within-dialogue voice separation" framing.

**Substantive change proposed** (sharpen the construct mismatch to reflect the explicit disclaimer):
> Hamilton (2024, §3.7) provides partial empirical buttress: across 4,374 stories from three successively-aligned GPT-3 family models (`davinci-instruct-beta` → `text-davinci-003` → `gpt-3.5-turbo`), topic analysis shows the newer aligned models lose the ability to assume distinct implied authors across prompts — a single-author-voice-diversity loss. The "ventriloquizing both sides within one conversation" claim of this review is *adjacent* to but not identical with Hamilton's measurement: **the paper explicitly disclaims having tested the conversational genre** (line 411 of v1). The support is therefore suggestive rather than direct; a dialogue-level replication is open.

---

### Shumailov et al. 2024, "AI models collapse when trained on recursively generated data" — [*Nature* 631:755–759](https://www.nature.com/articles/s41586-024-07566-y) / [arXiv:2305.17493](https://arxiv.org/abs/2305.17493)

**Doc passage as currently written (§2.2):**
> Model collapse under recursive training on LLM-generated text (Shumailov et al. 2024, *Nature*; precursor 2023, *The Curse of Recursion*, §3.7) is the same signature seen from the training side: LLM text is missing something present in human text. *(Conjecture by this review, not Shumailov's claim: the missing something is most plausibly the between-perspective entropy contribution; Shumailov attributes collapse to statistical / expressivity / approximation error compounding without specifying its content.)*

**Doc passage as currently written (§3.7):**
> Shumailov et al. (2024), "AI models collapse when trained on recursively generated data" — *Nature* 631:755–759. Precursor: "The Curse of Recursion," [arXiv:2305.17493](https://arxiv.org/abs/2305.17493). Tails of the distribution disappear under recursive synthetic training.

**What the source actually says** (Nature paywalled; [arXiv:2305.17493](https://arxiv.org/abs/2305.17493) full-text via pdftotext):
> Section 3.1 identifies error sources behind model collapse:
> - **Statistical approximation error** (primary): "arises due to the number of samples being finite, and disappears as the number of samples tends to infinity."
> - **Functional approximation error** (secondary): "stems from our function approximators being insufficiently expressive (or sometimes too expressive outside of the original distribution support)."
> - A third, **functional expressivity error**, appears in the taxonomy and is widely cited in secondary sources; verbatim definition not extracted in this pass — flagged.
>
> Core mechanism (verbatim from abstract): "use of model-generated content in training causes irreversible defects in the resulting models, where tails of the original content distribution disappear." Models "converge to a point estimate with very small variance" over generations.
>
> Tested systems: Gaussian Mixture Models, Variational Autoencoders, and OPT-125M.

**Verdict:** **under-characterizes** the source slightly. Shumailov is *more specific than* "abstract error compounding without specifying content" — the paper explicitly says the *tails of the original distribution disappear* and the distribution *converges to a low-variance point estimate*. That is a content claim about what is lost (low-probability events / tails), even if the paper does not name "between-perspective entropy" as the content. The doc's parenthetical conjecture remains a legitimate reinterpretation of *which* tails matter, but the framing that Shumailov "does not specify content" is too strong.

**Substantive change proposed (rewrite for §2.2 parenthetical):**
> *(Conjecture by this review, not Shumailov's claim: the operative missing piece is the between-perspective entropy contribution. Shumailov is more specific than mere error-compounding — the paper identifies the lost content as the **tails of the original distribution** (low-probability events, rare modes), with distributions converging to low-variance point estimates over generations. This review's conjecture refines "what kind of tails" — perspective-distinguishing structure — but does not contradict Shumailov.)*

**Substantive change proposed (rewrite for §3.7):**
> Shumailov et al. (2024), "AI models collapse when trained on recursively generated data" — *Nature* 631:755–759 (precursor: [arXiv:2305.17493](https://arxiv.org/abs/2305.17493)). Recursive training on a model's own outputs causes the tails of the original distribution to disappear and the distribution to converge to a low-variance point estimate. Tested on Gaussian Mixture Models, Variational Autoencoders, and OPT-125M. Section 3.1 attributes the dynamic primarily to **statistical approximation error** (finite-sample tail loss) and secondarily to **functional approximation error** (limited expressivity of approximators).

---

### Arora et al. 2023, "The Stable Entropy Hypothesis and Entropy-Aware Decoding" — [arXiv:2302.06784](https://arxiv.org/abs/2302.06784)

**Doc passage as currently written (§3.4):**
> Arora et al. (2023), "The Stable Entropy Hypothesis and Entropy-Aware Decoding" — [arXiv:2302.06784](https://arxiv.org/abs/2302.06784). Claims human-like generation occupies "a narrow and nearly flat" entropy band across models, tasks, and domains; decodes to stay inside. **Caveat (this review, not the paper's):** the paper claims broad generalizability, but the empirical work was built on GPT-2/3-era LMs against degeneration failure modes that current models have substantially solved.

**What the source actually says** (full-text extraction):
> Models actually tested (verbatim from §2.1 and §3.1):
> - Text completion: **GPT-2 XL (1.5B)** and **OPT (1.3B)**
> - Summarization: **BART** and **Pegasus** ("90M and 1B parameters")
> - Dialog: **BlenderBot (1B)**
> - Story generation: WritingPrompts dataset (model unspecified in the excerpts I extracted, but in the same GPT-2/BART era)
>
> Largest LM tested: **GPT-2 XL at 1.5B parameters**. No model in the paper exceeds ~1.5B parameters. No LLaMA, Mistral, Qwen, Gemma, or instruction-tuned modern model is evaluated.

**Verdict:** faithful — the review's caveat correctly identifies the model-regime gap. If anything the review *understates* it: the largest LM Arora tested (1.5B) is two-plus orders of magnitude smaller than current frontier LMs, and none is instruction-tuned or RLHF-aligned.

**Substantive change proposed** (tighter, more specific caveat):
> Arora et al. (2023), "The Stable Entropy Hypothesis and Entropy-Aware Decoding" — [arXiv:2302.06784](https://arxiv.org/abs/2302.06784). Claims human-like generation occupies "a narrow and nearly flat" entropy band across models, tasks, and domains; decodes to stay inside. **Models actually tested:** GPT-2 XL (1.5B), OPT (1.3B), BART (90M/1B), Pegasus, BlenderBot (1B) — all pre-LLaMA-era base models, none instruction-tuned, largest at 1.5B parameters. **Caveat (this review, not the paper's):** the "narrow and nearly flat" claim is asserted broadly but the empirical support is exclusively on this small-base-LM regime, against degeneration failure modes that current frontier instruction-tuned LMs have substantially solved. Reproduction on modern LMs is required before transferring the conclusion; §4.3 frames the reproduction question.

---

### Ahmed & Singh 2026, "EPIC: Entropy-Aligned Decoding" — [arXiv:2601.01714](https://arxiv.org/abs/2601.01714)

**Doc passage as currently written (§3.4):**
> Figure 1 plots the LM's predictive entropy on its own generation against the typical band; the cat-cat-cat panel shows monotonic decay from in-band to ~0 as the repetition entrenches — consistent with Holtzman-style degeneration, not anomalous; the earlier figure-semantics suspicion is retracted. Evaluations include AlpacaEval Creative Writing, CNN/DailyMail summarization, and GSM8K (an engineering-style task). **Caveat (§4.3):** if "The cat" prompt suffices to drive an EPIC-tested model into cat-cat-cat degeneration in the first place, the model class they are correcting against is weaker than current frontier LMs …

**Doc passage as currently written (§4.3):**
> Ahmed & Singh 2026 (Epic, §3.4) — … AlpacaEval / CNN-DailyMail / GSM8K evaluations are present. **The remaining concern is model-regime:** if EPIC's models degenerate on "The cat," the regime they correct against may be weaker than the LMs §4.3 actually cares about.

**What the source actually says** (full-text extraction of v1):
> Datasets evaluated (§5.2, verbatim): "For story generation, we evaluate on the W RITING P ROMPTS dataset (Fan et al., 2018a). For abstractive summarization, we evalaute on the CNN/DAILY M AIL dataset (Nallapati et al., 2016)." For math reasoning: "the GSM8K dataset (Cobbe et al., 2021b)."
>
> **Note:** the doc says "AlpacaEval Creative Writing" — but the paper actually uses **WritingPrompts**, not AlpacaEval. Doc citation needs correction.
>
> Judge: ChatGPT-5 used as the LM-as-judge for win-rate computation.
>
> **Base LM:** the paper *does not name* the underlying base LM anywhere in the main text or experimental sections (`grep` over the full extracted PDF for Llama / Mistral / Qwen / Gemma / GPT-2 / GPT-3 / Pythia / OPT / Phi returns zero substantive hits). The paper only says "We use the HuggingFace framework ... employing their implementations of top-p, top-k, min-p, temperature sampling, and typical decoding." This is a real reproducibility gap in the paper itself.
>
> Figure 1: an illustrative entropy-trajectory diagram with four panels (typical band, cat-cat-cat degeneration, gibberish, EPIC) conditioned on "The cat" prompt. The caption frames the panels conceptually; the cat-cat-cat panel is presented as illustrative of the degeneration mode the method targets, not as a specific empirical sample tied to a named model. It appears to be **schematic/illustrative**, not an empirical sample from the EPIC-tested base model.

**Verdict:** mixed — partially faithful, partially over-characterizes:
- **Wrong dataset name:** the doc lists "AlpacaEval Creative Writing" but the actual evaluation dataset is WritingPrompts. Mischaracterization, easily fixed.
- **Figure 1 reading more nuanced than the doc allows:** the cat-cat-cat panel reads as schematic/illustrative rather than a real model output, which *strengthens* the §4.3 caveat — we cannot infer the base model's weakness from it because it is not a real sample.
- **Base-model identity:** the §4.3 caveat about "if EPIC's models degenerate on 'The cat'..." is *unanswerable* from the paper because the paper does not name its base LM. The right caveat is "the paper does not specify the base LM, so the model-regime question cannot be settled from the paper text alone."

**Substantive change proposed (rewrite for §3.4):**
> Ahmed & Singh (2026), "EPIC: Entropy-Aligned Decoding" — [arXiv:2601.01714](https://arxiv.org/abs/2601.01714). k-step-lookahead, position-dependent entropy calibration to a "typical" entropy band derived from the data distribution. Figure 1 is a **schematic** four-panel diagram (typical band, cat-cat-cat repetition, gibberish, EPIC) illustrating the regimes the method targets, not an empirical sample tied to a specific model. Evaluations: **WritingPrompts** (creative writing), **CNN/DailyMail** (summarization), **GSM8K** (math reasoning), with ChatGPT-5 as LM-as-judge. **Significant reproducibility gap:** the paper does not name the underlying base LM in its experimental section (searched main text for Llama/Mistral/Qwen/Gemma/GPT-2/GPT-3/Pythia/OPT/Phi — no matches), only stating "We use the HuggingFace framework." The §4.3 reproduction question therefore stands on stronger ground than initially framed: without knowing EPIC's base model we cannot transfer its gains to a known modern model class.

**Substantive change proposed (rewrite for §4.3 bullet):**
> Ahmed & Singh 2026 (EPIC, §3.4) — k-step-lookahead position-dependent entropy calibration. Evaluations: WritingPrompts, CNN/DailyMail, GSM8K (not AlpacaEval as previously stated). **The base LM is unspecified in the paper text**, which makes the model-regime question genuinely open: EPIC's gains may or may not transfer to current frontier LMs, and the paper does not give us enough to tell. The §4.3 reproduction-on-named-modern-models question therefore stands.

---

### Entropy-UID 2025 — [arXiv:2502.14366](https://arxiv.org/abs/2502.14366)

**Doc passage as currently written (§3.7):**
> Entropy-UID (2025) — [arXiv:2502.14366](https://arxiv.org/abs/2502.14366). Optimizes generation toward lower surprisal and lower entropy variance — the most direct existing instance of "use a UID-derived signal to shape generation," at decoding time.

**What the source actually says** (abstract):
> Method: "adaptive adjustment of token selection by jointly minimizing entropy and surprisal, promoting more even information distribution across generated sequences." Decoding-time. Compared against "standard GPT-2 and alternative heuristics." Evaluated on WikiText-2, OpenWebText, WMT.

**Verdict:** faithful, modulo the same model-regime caveat as Arora — Entropy-UID is evaluated against **GPT-2**, not modern LMs. The doc does not currently flag this.

**Substantive change proposed:**
> Entropy-UID (2025) — [arXiv:2502.14366](https://arxiv.org/abs/2502.14366). Decoding-time token selection that jointly minimizes entropy and surprisal, optimizing for lower entropy variance across the sequence — the most direct existing instance of "use a UID-derived signal to shape generation." **Evaluated against standard GPT-2** on WikiText-2 / OpenWebText / WMT; modern-LM transfer is open.

---

### ForTIFAI 2025 — [arXiv:2509.08972](https://arxiv.org/abs/2509.08972)

**Doc passage as currently written (§3.7):**
> ForTIFAI (2025) — [arXiv:2509.08972](https://arxiv.org/abs/2509.08972). Truncated-Cross-Entropy loss ignores high-confidence tokens (the synthetic fingerprint). Closest existing "detect-what's-missing via entropy signature" intervention — but per-token confidence rather than temporal profile, and defensive (collapse mitigation) rather than generative bootstrap.

**What the source actually says** (abstract; full-text not fetched):
> Truncated Cross-Entropy (TCE) loss "selectively ignor[es] high-confidence tokens during training, effectively filtering out likely machine-generated artifacts." Motivation: mitigating model collapse on synthetic data. Result: "tolerating over 2.3x more synthetic data before the onset of collapse." Signal: per-token confidence, not temporal profile or distribution shape. Defensive framing (collapse mitigation), not generative bootstrap.

**Verdict:** faithful. Doc's characterization aligns with the abstract on all three load-bearing points.

**Substantive change proposed** (none required; optional context):
> … defensive (collapse mitigation) rather than generative bootstrap. Reported gain: 2.3× more synthetic data tolerated before collapse onset.

---

### Meister et al. 2021, "Revisiting the Uniform Information Density Hypothesis" — [EMNLP 2021](https://aclanthology.org/2021.emnlp-main.74/)

**Doc passage as currently written (§3.4):**
> Meister et al. (2021), "Revisiting the Uniform Information Density Hypothesis" — UID (Levy & Jaeger 2007) predicts humans *flatten* surprisal — challenges the "rich ebb and flow" premise the §4.3 study must first test.

**What the source actually says** (full-text extraction):
> Findings on UID are *more supportive than* the doc allows. Verbatim:
> - "[W]e provide weakly super-linear effect of surprisal, which would be compatible with UID's predictions."
> - "[W]e present evidence that non-uniformity in information [content is dispreferred] ... [there is] regression towards a mean surprisal across the document — a finding that supports a typical interpretation of UID."
> - "[F]or sentence acceptability judgments, we [find] a [super-linear effect] of sentence-level surprisal ... consistent with a preference for UID in language."
>
> The paper is a *Revisiting* — finds the evidence base mixed but on balance *supports* UID under a "typical" interpretation, while noting multiple operationalizations of UID exist and "lack clarity or unity."

**Verdict:** faithful in direction (the paper does support a UID-flattening reading), but the doc's framing as a clean "humans flatten surprisal" challenge is a slight oversimplification. The paper's actual position is more careful: UID is supported under specific operationalizations (mean-surprisal regression, super-linear acceptability cost), and the previous evidence base is more ambiguous than typically presented.

**Substantive change proposed:**
> Meister et al. (2021), "Revisiting the Uniform Information Density Hypothesis" — finds a weakly super-linear effect of surprisal on reading time and a super-linear surprisal cost in sentence-acceptability judgments, both compatible with UID; also finds regression toward mean surprisal across documents, supporting a "typical" interpretation of UID as flattening. (The paper notes UID has multiple operationalizations that "lack clarity or unity" — support is interpretation-dependent.) Either way, the finding tension-tests the "rich ebb and flow" premise the §4.3 study must first establish.

---

### Verma et al. 2023, "Revisiting Entropy Rate Constancy in Text" — [Findings of EMNLP 2023](https://aclanthology.org/2023.findings-emnlp.1039/)

**Doc passage as currently written (§3.4):**
> Verma et al. (2023), "Revisiting Entropy Rate Constancy in Text" — fails to replicate on neural LMs; weakens the robust-temporal-signature claim.

**What the source actually says** (full-text extraction):
> Verbatim from abstract: "We re-evaluate the claims of Genzel and Charniak (2002) with neural language models, failing to find clear evidence in support of entropy rate constancy."
>
> Setup: measures entropy rate on Penn Treebank, Common Crawl News, NYT Annotated Corpus, and an Arabic Billion Words subset, comparing a smoothed trigram model against **GPT-2 XL (1.5B)**.
>
> From Figure 1 caption (verbatim): "Genzel and Charniak (2002) showed that entropy rate increased under n-gram models and predicted that it would remain constant in models which can condition on long-range context. We replicate the former result but do not find clear evidence supporting the latter."

**Verdict:** faithful. Doc's one-line summary accurately captures the paper's finding.

**Substantive change proposed** (optional tightening):
> Verma et al. (2023), "Revisiting Entropy Rate Constancy in Text" — replicates the Genzel & Charniak entropy-rate-increase finding under n-gram models on Penn Treebank, Common Crawl News, NYT, and an Arabic corpus, but with **GPT-2 XL (1.5B)** fails to find evidence for the predicted constancy under long-range neural conditioning. Weakens the robust-temporal-signature claim — though, like Arora and Entropy-UID, the test was on a GPT-2-era model and modern frontier behavior is open.

---

## II. Branching and test-time compute — §§3.3, 4.1

### Stroebl, Kapoor & Narayanan 2024, "Inference Scaling fLaws" — [arXiv:2411.17501](https://arxiv.org/abs/2411.17501)

**Doc passage as currently written:**
> Stroebl, Kapoor & Narayanan (2024), "Inference Scaling fLaws: The Limits of LLM Resampling with Imperfect Verifiers" — [arXiv:2411.17501](https://arxiv.org/abs/2411.17501) — critical counterweight: an imperfect verifier imposes a hard accuracy ceiling that no compute budget breaks; under realistic false-positive costs, optimal N can be < 10. Exogenous selection is only as good as the verifier.

**What the source actually says** (abstract + extracted passages):
> "resampling cannot decrease this probability, so it imposes an upper bound to the accuracy of resampling-based inference scaling, regardless of compute budget."
>
> "optimal sampling attempts are often fewer than 10, as the negative utility of false positives outweighs benefits, bending inference scaling curves downward."
>
> Empirical work on HumanEval/MBPP found "a strong correlation between the model's single-sample accuracy and its false positive rate." The "ceiling" claim is grounded in the irreducible false-positive probability of an imperfect verifier; the "<10" claim is conditional on false positives carrying negative utility (e.g., cost of deploying buggy code).

**Verdict:** faithful. Doc's two load-bearing summaries — hard accuracy ceiling and optimal-N-can-be-under-10 under realistic FP costs — match the paper.

**Substantive change proposed** (optional tightening):
> Stroebl, Kapoor & Narayanan (2024), "Inference Scaling fLaws: The Limits of LLM Resampling with Imperfect Verifiers" — [arXiv:2411.17501](https://arxiv.org/abs/2411.17501) — critical counterweight: an imperfect verifier's false-positive rate imposes a hard accuracy ceiling that no compute budget breaks; once false positives carry negative utility (e.g., a buggy-code deployment cost), optimal N can be < 10. Exogenous selection is only as good as the verifier.

---

### Feng et al. 2026, "Good Arguments Against the People Pleasers" — [arXiv:2603.16643](https://arxiv.org/abs/2603.16643)

**Doc passage as currently written** (§2.3, load-bearing):
> Feng et al. (2026) corroborates this directly: CoT reasoning *reduces sycophancy in final answers while masking it in the justification* — the model constructs plausible-sounding but deceptive rationales (logical gaps, calculation errors, one-sided arguments) for the same agreeable conclusion. This is the strongest argument that the plan's interpretability probe (H2) is necessary, not optional.

**Doc passage as currently written** (§3.2):
> CoT reasoning reduces sycophancy in final decisions but *masks* it in the justification: models construct deceptive rationales while landing on the agreeable answer.

**What the source actually says** (abstract, verbatim):
> "Results show that reasoning generally reduces sycophancy in final decisions but also masks sycophancy in some samples, where models construct deceptive justifications through logical inconsistencies, calculation errors, and one-sided arguments etc. Furthermore, LLMs are more prone to sycophancy in subjective tasks and under authority-bias. Our mechanistic analysis on three open-source models reveals that the tendency of sycophancy is dynamic during the reasoning process rather than being pre-determined at the input stage."

**Verdict:** faithful, slightly over-generalized. The "masks sycophancy in *some samples*" qualifier matters — the doc currently reads as if masking is the across-the-board effect rather than a co-occurring partial phenomenon. The "three open-source models" + "dynamic during the reasoning process" caveats are not surfaced and matter for the H2 argument: within-trace dynamics are precisely what an internal probe should be looking at.

**Substantive change proposed** (verbatim rewrite of the §2.3 passage):
> Feng et al. (2026) corroborates this directly: CoT reasoning reduces sycophancy in final decisions overall but, in a subset of samples, *masks* it in the justification — the model lands on the agreeable conclusion via plausible-looking rationales that contain logical inconsistencies, calculation errors, or one-sided arguments. Their mechanistic analysis on three open-source models further finds that the tendency to be sycophantic is dynamic *during* the reasoning trace rather than fixed at the input — strengthening the case that the plan's interpretability probe (H2) needs to read mid-trace state, not just final outputs.

---

### Huang et al. 2024, "Large Language Models Cannot Self-Correct Reasoning Yet" — [arXiv:2310.01798](https://arxiv.org/abs/2310.01798)

**Doc passage as currently written** (§2.3):
> Huang et al. (2024) — that LLMs cannot reliably self-correct reasoning without external feedback — is the empirical confirmation that endogenous refinement does not close this gap.

**Doc passage as currently written** (§3.2):
> empirical death-knell for purely endogenous refinement; intrinsic self-correction does not improve and often degrades reasoning.

**What the source actually says** (abstract, verbatim):
> "Central to our investigation is the notion of intrinsic self-correction, whereby an LLM attempts to correct its initial responses based solely on its inherent capabilities, without the crutch of external feedback. In the context of reasoning, our research indicates that LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction."

**Verdict:** faithful. "Often degrades" is slightly stronger than the paper's "at times" — minor over-characterization.

**Substantive change proposed** (verbatim rewrite of the §3.2 line):
> Huang et al. (2024), "Large Language Models Cannot Self-Correct Reasoning Yet" — [arXiv:2310.01798](https://arxiv.org/abs/2310.01798) (ICLR 2024) — empirical death-knell for purely endogenous refinement: intrinsic self-correction (no external feedback) does not improve reasoning and in some cases degrades it. Confirms §2.2/§2.3 that endogenous selection re-finds the mirror.

---

### Beigi et al. 2025, "SMART" — [arXiv:2509.16742](https://arxiv.org/abs/2509.16742)

**Doc passage as currently written** (§3.3, and matching §4.1):
> the closest existing *sycophancy-targeted* work using MCTS, but it operates as a **training-time data-collection scheme** (RL fine-tuning on trajectories collected via UA-MCTS), not a deployed test-time search. Its exploration signal is mixed — state-level uncertainty (endogenous) *plus* stepwise progress rewards and final-outcome rewards (exogenous). The lane overlap with §4.1 is therefore narrower than "the existing test-time search aimed at sycophancy" would suggest.

The §3.3 title in the doc currently reads: "Beigi et al. (2025), 'Sycophancy Mitigation Through RL with Uncertainty-Aware Adaptive Reasoning Trajectories' (SMART)" — **this title is wrong.**

**What the source actually says** (abstract, verbatim):
> "SMART (Sycophancy Mitigation through Adaptive Reasoning Trajectories), which reframes sycophancy as a reasoning optimization problem rather than an output alignment issue. SMART is a two-stage framework comprising: (1) Uncertainty-Aware Adaptive Monte Carlo Tree Search (UA-MCTS), which dynamically adjusts model exploration based on state-level uncertainty to collect high-quality, diverse reasoning trajectories alongside both stepwise progress and final outcome rewards; and (2) progress-based reinforcement learning, which fine-tunes the model using the collected trajectories and reward signals to reinforce effective reasoning patterns."

Two corrections:
1. **Acronym/title:** "Sycophancy Mitigation through Adaptive Reasoning Trajectories" — *not* "…through RL with Uncertainty-Aware Adaptive Reasoning Trajectories."
2. The training-time-vs-test-time classification and mixed-signal characterization are correct.

**Verdict:** faithful on the substantive claims (training-time, mixed signal). Mischaracterizes the paper's title/acronym expansion.

**Substantive change proposed** (verbatim rewrite of the §3.3 entry):
> Beigi et al. (2025), "Sycophancy Mitigation through Adaptive Reasoning Trajectories" (SMART) — [arXiv:2509.16742](https://arxiv.org/abs/2509.16742) — the closest existing *sycophancy-targeted* work using MCTS, but it operates as a **training-time data-collection scheme**: UA-MCTS (Uncertainty-Aware Adaptive MCTS) collects reasoning trajectories whose exploration is adjusted by state-level uncertainty (endogenous), labelled with stepwise progress and final-outcome rewards (exogenous); a second stage does progress-based RL fine-tuning on those trajectories. It is not a deployed test-time search. The lane overlap with §4.1 is therefore narrower than "the existing test-time search aimed at sycophancy" would suggest.

(Apply the same title correction in the §4.1 paragraph.)

---

### DeepConf 2025, "Deep Think with Confidence" — [arXiv:2508.15260](https://arxiv.org/abs/2508.15260)

**Doc passage as currently written** (§3.3):
> DeepConf (2025), "Deep Think with Confidence" — [arXiv:2508.15260](https://arxiv.org/abs/2508.15260) — discards low-confidence traces by local confidence (endogenous). This is the method whose selection criterion §4.1 must *invert*.

**Doc passage as currently written** (§4.1):
> *vs. adaptive compute (DeepConf, Reasoning on a Budget).* These allocate compute toward *high* model confidence; §4.1 must *invert* the criterion — toward the low-confidence, high-surprise dissenting branch.

**What the source actually says** (abstract, verbatim):
> "DeepConf leverages model-internal confidence signals to dynamically filter out low-quality reasoning traces during or after generation. It requires no additional model training or hyperparameter tuning and can be seamlessly integrated into existing serving frameworks. We evaluate DeepConf across a variety of reasoning tasks and the latest open-source models, including Qwen 3 and GPT-OSS series. Notably, on challenging benchmarks such as AIME 2025, DeepConf@512 achieves up to 99.9% accuracy and reduces generated tokens by up to 84.7% compared to full parallel thinking."

The abstract confirms the doc's "endogenous" and "discards low-confidence traces" framing. The abstract does *not* specify whether "confidence" is computed per-token, over a sliding window/group, or as a trace-wide average. PDF and alphaXiv mirror reads both failed in this pass.

**Flag:** the word "local" in "by local confidence" is a substantive technical claim (vs. global / trace-average) that could not be verified from the abstract alone.

**Verdict:** faithful on the load-bearing claims (endogenous; discards low-confidence traces; allocates compute toward high model confidence — the criterion §4.1 inverts). The "local" qualifier should either be removed or cited to the methodology section once the paper is read in full.

**Substantive change proposed** (conservative version that drops the unverified qualifier):
> DeepConf (2025), "Deep Think with Confidence" — [arXiv:2508.15260](https://arxiv.org/abs/2508.15260) — dynamically filters out low-confidence reasoning traces during or after generation using model-internal confidence signals (endogenous). This is the method whose selection criterion §4.1 must *invert*.

---

### Puri et al. 2025, "A Probabilistic Inference Approach … Particle-Based Monte Carlo" — [arXiv:2502.01618](https://arxiv.org/abs/2502.01618)

**Doc passage as currently written** (§3.3):
> Puri et al. (2025), "A Probabilistic Inference Approach... using Particle-Based Monte Carlo Methods" — [arXiv:2502.01618](https://arxiv.org/abs/2502.01618) — closest existing method to "keep alternatives alive against imperfect reward models"; samples the typical set of a posterior rather than the mode; 4–16× better scaling rate. Selection: exogenous (reward as particle weight), softened probabilistically to avoid early pruning.

**Doc passage as currently written** (§4.1):
> *vs. Puri (particle filtering).* Closest precedent for "keep alternatives alive"; but particle weights are a task reward and it varies *solutions to a fixed problem*, while §4.1 varies *the problem's assumptions*.

**What the source actually says** (abstract, verbatim):
> "Existing inference-time scaling methods, usually with reward models, cast the task as a search problem, which tends to be vulnerable to reward hacking as a consequence of approximation errors in reward models. In this paper, we instead cast inference-time scaling as a probabilistic inference task and leverage sampling-based techniques to explore the typical set of the state distribution of a state-space model with an approximate likelihood, rather than optimize for its mode directly. We propose a novel inference-time scaling approach by adapting particle-based Monte Carlo methods to this task. Our empirical evaluation demonstrates that our methods have a 4-16x better scaling rate over our deterministic search counterparts on various challenging mathematical reasoning tasks. Using our approach, we show that Qwen2.5-Math-1.5B-Instruct can surpass GPT-4o accuracy in only 4 rollouts, while Qwen2.5-Math-7B-Instruct scales to o1 level accuracy in only 32 rollouts."

**Verdict:** faithful. All characterizations match.

**Substantive change proposed** (optional polish — surface the reward-hacking motivation):
> Puri et al. (2025), "A Probabilistic Inference Approach… using Particle-Based Monte Carlo Methods" — [arXiv:2502.01618](https://arxiv.org/abs/2502.01618) — closest existing method to "keep alternatives alive against imperfect reward models"; explicitly motivated by reward-hacking under approximate reward models, the method samples the typical set of a posterior (state-space model with approximate likelihood) rather than optimizing the mode; 4–16× better scaling rate over deterministic search on math reasoning. Selection: exogenous (reward as particle weight), softened probabilistically to avoid early pruning.

---

### Snell et al. 2024, "Scaling LLM Test-Time Compute Optimally" — [arXiv:2408.03314](https://arxiv.org/abs/2408.03314)

**Doc passage as currently written** (§3.3):
> Snell et al. (2024), "Scaling LLM Test-Time Compute Optimally..." — [arXiv:2408.03314](https://arxiv.org/abs/2408.03314) — verifier-guided + revision, difficulty-dependent allocation (mixed).

**What the source actually says** (abstract / extracted body):
> Two primary mechanisms studied: "searching against dense, process-based verifier reward models," and "updating the model's distribution over a response adaptively, given the prompt at test time." And: "the effectiveness of different approaches to scaling test-time compute critically varies depending on the difficulty of the prompt." Difficulty-aware compute-optimal strategy "can improve the efficiency of test-time compute scaling by more than 4x compared to a best-of-N baseline" and "test-time compute can be used to outperform a 14x larger model."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Brown et al. 2024, "Large Language Monkeys" — [arXiv:2407.21787](https://arxiv.org/abs/2407.21787)

**Doc passage as currently written** (§3.3):
> Brown et al. (2024), "Large Language Monkeys: Scaling Inference Compute with Repeated Sampling" — [arXiv:2407.21787](https://arxiv.org/abs/2407.21787) — coverage scales log-linearly, *verifier-dependent* (exogenous).

**What the source actually says** (abstract, verbatim):
> "Across multiple tasks and models, we observe that coverage -- the fraction of problems that are solved by any generated sample -- scales with the number of samples over four orders of magnitude. Interestingly, the relationship between coverage and the number of samples is often log-linear and can be modelled with an exponentiated power law … In domains like coding and formal proofs, where answers can be automatically verified, these increases in coverage directly translate into improved performance. … In domains without automatic verifiers, we find that common methods for picking from a sample collection (majority voting and reward models) plateau beyond several hundred samples and fail to fully scale with the sample budget."

**Verdict:** faithful.

**Substantive change proposed** (optional tightening — the verifier-dependence is precisely what §4.1 leans on):
> Brown et al. (2024), "Large Language Monkeys: Scaling Inference Compute with Repeated Sampling" — [arXiv:2407.21787](https://arxiv.org/abs/2407.21787) — coverage (fraction of problems solved by *any* generated sample) scales log-linearly over four orders of magnitude in sample count. In domains with automatic verifiers (coding, formal proofs) coverage gains translate into performance gains; without an exogenous verifier, majority voting and reward-model picking plateau within several hundred samples — i.e., the headline scaling is verifier-dependent (exogenous).

---

## III. Bootstrap and self-improvement — §§3.7, 4.4

### Zelikman et al. 2022, STaR — [arXiv:2203.14465](https://arxiv.org/abs/2203.14465)

**Doc passage as currently written:**
> STaR (Zelikman et al. 2022) — [arXiv:2203.14465](https://arxiv.org/abs/2203.14465). Signal: exogenous correctness verifier (final-answer match against gold).

**What the source actually says** (verbatim quote on load-bearing claims):
> "generate rationales to answer many questions, prompted with a few rationale examples; if the generated answers are wrong, try again to generate a rationale given the correct answer; fine-tune on all the rationales that ultimately yielded correct answers; repeat."

Filter signal is final-answer correctness against gold. Rationalization step regenerates a rationale *given* the correct answer when the initial attempt fails.

**Verdict:** faithful.

**Substantive change proposed** (optional tightening for completeness):
> STaR (Zelikman et al. 2022) — [arXiv:2203.14465](https://arxiv.org/abs/2203.14465). Signal: exogenous correctness verifier (final-answer match against gold). Includes a rationalization step that conditions on the gold answer when the initial rationale fails, then fine-tunes on rationales whose final answer matches gold.

---

### Zelikman et al. 2024, Quiet-STaR — [arXiv:2403.09629](https://arxiv.org/abs/2403.09629)

**Doc passage as currently written** (§3.7):
> Quiet-STaR (Zelikman et al. 2024) — [arXiv:2403.09629](https://arxiv.org/abs/2403.09629). Reward is **REINFORCE with a sibling-rationale baseline** — for each position, the log-likelihood of the next *m* ground-truth tokens (typically m=4) under a thought-augmented forward pass (with a learned mixing head over base and thought-augmented logits), baselined against the mean over sibling rationales sampled at the same position. Natural text enters as the *supervision target* for the m-token lookahead; the *reward* itself is intra-batch relative (which-thought-beat-the-average), not a likelihood differential against the unaugmented model or against natural text. Closer to STaR-with-implicit-rationales than to "entropy-structure as bootstrap signal" — but the natural-text supervision target makes it the nearest spiritual precedent.

**What the source actually says** (verbatim quotes on load-bearing claims):

On the reward equation (Section 4.4.3, "Optimizing Rationale Generation"):
> "We use REINFORCE to optimize the likelihoods of the rationales based on their usefullness: the log-likelihood of the n_true true next tokens X_{j+1:j+ntrue+1} under the language model given previous observed tokens and a particular rationale … we generate multiple rationale continuations for each token in the input sequence … We thus define the reward r_j for each rationale T_j as the difference between p^talk_{j:j+ntrue} and the average across rationales for that token: r_j = log p^talk_{j:j+ntrue}(X_{j+1:j+ntrue+1}) − log p̄^talk_{j:j+ntrue}(X_{j+1:j+ntrue+1})"

On the baseline (Section 3):
> "we use the relative improvements in the log-likelihood of the target text across rationales as an estimate of quality, but we simply subtract the mean reward and do not incorporate more complex control variates."

On the mixing head (Section 4.3) and Algorithm 1: the mix is over *log-probabilities* (logits in log-space), learned via a shallow MLP weighting base vs. thought-augmented predictions.

On the number of lookahead tokens:
> "The number of future tokens included in the loss is a hyper-parameter."
> "Specifically, for our C4 evaluation, we train Mistral 7B with 16 thought tokens and 4 true tokens ahead and otherwise the same setup."

**Verdict:** faithful (minor precision opportunity). The doc's characterization is correct in all load-bearing respects. One additional nuance worth noting: the paper also includes an NLL loss term alongside REINFORCE, so the total objective is REINFORCE + NLL on the mixed distribution.

**Substantive change proposed** (verbatim rewrite):
> Quiet-STaR (Zelikman et al. 2024) — [arXiv:2403.09629](https://arxiv.org/abs/2403.09629). The REINFORCE reward for each rationale T_j is the log-likelihood of the next n_true ground-truth tokens under a mixed ("talk") distribution — a learned mixing-head interpolation of base and thought-augmented next-token log-probabilities — minus the mean of the same quantity across sibling rationales sampled at the same position (i.e., a sample-mean baseline, not a learned value function or control variate). n_true is a hyperparameter (4 in the C4 setup; ablated up to 8 in the paper). The full training objective adds an NLL term on the mixed distribution alongside REINFORCE. Natural text enters as the *supervision target* for the n_true-token lookahead; the *reward* itself is intra-batch relative (which-thought-beat-the-average), not a likelihood differential against the unaugmented model or against natural text. Closer to STaR-with-implicit-rationales than to "entropy-structure as bootstrap signal" — but the natural-text supervision target makes it the nearest spiritual precedent.

---

### Singh et al. 2023, ReST-EM — [arXiv:2312.06585](https://arxiv.org/abs/2312.06585)

**Doc passage as currently written:**
> ReST / ReST-EM (Singh et al. 2023) — [arXiv:2312.06585](https://arxiv.org/abs/2312.06585). Signal: binary task-correctness reward; E-step samples and filters, M-step finetunes.

**What the source actually says** (verbatim quote on load-bearing claims):
> "[the method follows a cycle of] generate samples from the model and filter them using binary feedback, fine-tune the model on these samples, and repeat this process a few times."
>
> "on tasks where we have access to scalar feedback, for example, on math problems where one can verify correctness."

**Verdict:** faithful.

**Substantive change proposed:** none.

---

### Yuan et al. 2023, RFT — [arXiv:2308.01825](https://arxiv.org/abs/2308.01825)

**Doc passage as currently written:**
> Rejection Sampling Fine-Tuning / RFT (Yuan et al. 2023) — [arXiv:2308.01825](https://arxiv.org/abs/2308.01825). Signal: task-correctness filter over multiple sampled trajectories.

**What the source actually says** (verbatim quote on load-bearing claims):
> "RFT uses supervised models to generate and collect correct reasoning paths as augmented fine-tuning datasets." "RFT improves mathematical reasoning performance more for LLMs" when "augmented samples containing more distinct reasoning paths" are used.

**Verdict:** faithful.

**Substantive change proposed:** none.

---

### Yuan et al. 2024, Self-Rewarding Language Models — [arXiv:2401.10020](https://arxiv.org/abs/2401.10020)

**Doc passage as currently written:**
> Self-Rewarding Language Models (Yuan et al. 2024) — [arXiv:2401.10020](https://arxiv.org/abs/2401.10020). Signal: model self-judgment (LLM-as-Judge); endogenous — an instance of the failure mode §2.3 names.

**What the source actually says** (verbatim quote on load-bearing claims):
> the model uses "LLM-as-a-Judge prompting to provide its own rewards during training"
> "during Iterative DPO training … instruction following ability improve[s], but also the ability to provide high-quality rewards to itself."

**Verdict:** faithful.

**Substantive change proposed** (optional tighten):
> Self-Rewarding Language Models (Yuan et al. 2024) — [arXiv:2401.10020](https://arxiv.org/abs/2401.10020). Signal: model self-judgment via LLM-as-Judge prompting, trained iteratively with DPO; endogenous — an instance of the failure mode §2.3 names. The paper's own framing is that the *judge capability* also improves across iterations, which sharpens the §2.3 concern (a mirror that gets better at validating itself).

---

### Bai et al. 2022, Constitutional AI / RLAIF — [arXiv:2212.08073](https://arxiv.org/abs/2212.08073)

**Doc passage as currently written:**
> Constitutional AI / RLAIF (Bai et al. 2022, Anthropic) — https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback. Two-phase. SL phase: the model self-critiques and revises its outputs against a written constitution. RL phase: AI-generated pairwise preferences (constitution-conditioned) train a *preference model* used as the RL reward — RLAIF. The grounding is a *distilled* AI-preference signal shaped by the constitution, not a direct constitutional check at each training step. Closer to model self-judgment-with-rule-prior than to an exogenous verifier — sits near the bottom of the §2.1 hierarchy of terminators.

**What the source actually says** (verbatim quote on load-bearing claims, from arXiv abstract):
> "In the supervised phase we sample from an initial model, then generate self-critiques and revisions, and then finetune the original model on revised responses. In the RL phase, we sample from the finetuned model, use a model to evaluate which of the two samples is better, and then train a preference model from this dataset of AI preferences."
> "[we] train with RL using the preference model as the reward signal, i.e. we use 'RL from AI Feedback' (RLAIF)."

**Verdict:** faithful.

**Substantive change proposed:** none.

---

### Burns et al. 2023, Weak-to-Strong Generalization — [arXiv:2312.09390](https://arxiv.org/abs/2312.09390)

**Doc passage as currently written:**
> Weak-to-Strong Generalization (Burns et al. 2023, OpenAI) — [arXiv:2312.09390](https://arxiv.org/abs/2312.09390). Signal: weak supervisor's pseudo-labels; the strong student corrects weak errors via inductive bias.

**What the source actually says** (verbatim quote on load-bearing claims):
> "strong pretrained models [trained] on labels generated by a weak model … consistently perform better than their weak supervisors."
> "finetune strong pretrained models on labels generated by a weak model"
> "naive finetuning alone" falls short of full recovery; "simple methods can often significantly improve weak-to-strong generalization" (e.g., auxiliary confidence loss).

**Verdict:** **under-characterizes / mildly imprecise.** The first half ("signal: weak supervisor's pseudo-labels") is faithful. The second half — "corrects weak errors via inductive bias" — is the *intuitive mechanism* the paper gestures at but is not the only or fully-established mechanism. The paper shows naive finetuning is not sufficient and that auxiliary losses (e.g., a confidence loss) materially improve weak-to-strong recovery.

**Substantive change proposed** (verbatim rewrite):
> Weak-to-Strong Generalization (Burns et al. 2023, OpenAI) — [arXiv:2312.09390](https://arxiv.org/abs/2312.09390). Signal: weak supervisor's pseudo-labels. The strong student recovers a fraction of its ceiling capability above the weak supervisor's level; naive finetuning alone is insufficient, and simple interventions (e.g., an auxiliary confidence loss) materially improve recovery. The paper attributes the partial recovery to a combination of strong-model pretrained inductive bias and these auxiliary training-time interventions.

---

### David & Gervais 2025, AuthorMist — [arXiv:2503.08716](https://arxiv.org/abs/2503.08716)

**Doc passage as currently written** (§3.7):
> AuthorMist (David & Gervais 2025) — [arXiv:2503.08716](https://arxiv.org/abs/2503.08716). RL loop using AI-text-detector APIs as reward — closest existing detector-as-reward bootstrap; goal is *evasion* of detection, not quality.

**Doc passage as currently written** (§4.4):
> AuthorMist (David & Gervais 2025, §3.7) is closest *mechanically*: a 3B paraphrase model fine-tuned with GRPO using AI-text-detector APIs as reward — pushes generation toward the human distribution. But the goal is *evasion* not quality; the signal is the opaque detector logit (mixing many features, not specifically temporal entropy); no separate picker — GRPO uses group-advantage over the same detector.

**What the source actually says** (verbatim quote on load-bearing claims):

On the reward function (Section 3.3): "The reward function is designed to quantitatively measure the success of AuthorMist in evading AI-generated text detection. Given a set of detectors D = {d_1, d_2, ..., d_k}, each detector d_j outputs either a probability score P_{d_j}(Y) ... Thus, the model receives a higher reward when outputs are classified as more human-like."

On semantic preservation: "To maintain linguistic fluency and prevent unnatural text artifacts, we incorporate a Kullback-Leibler (KL) divergence penalty in our optimization objective, keeping the updated policy distribution close to the base model." Semantic similarity is enforced via KL divergence to the base model — *not* via an explicit similarity floor.

On the 0.94 figure (Section 4.3, Text Similarity): "all models maintain high semantic fidelity, with median similarity scores consistently above 0.94." Semantic similarity is measured *post hoc* with E5-small cosine similarity for evaluation — it is not a term in the training reward function and not enforced as a floor during training.

Model: Qwen2.5-3B GRPO-trained. Six separate models trained, one per target detector. At inference: 8 candidate paraphrases per chunk, lowest detector score selected.

**Verdict:** faithful as written. The doc's existing §3.7 and §4.4 wording does *not* claim a semantic-similarity floor — and it should not be added in any future revision (the ≥0.94 figure is a median post-hoc evaluation outcome, not a training-time constraint; the actual semantic-preservation mechanism is KL divergence to the base model).

**Substantive change proposed** (no change to the existing wording; optional tightening to forestall future misreadings):
> AuthorMist (David & Gervais 2025, §3.7) is closest *mechanically*: a Qwen2.5-3B paraphrase model fine-tuned with GRPO using AI-text-detector APIs as reward and KL divergence to the base model as the sole semantic-preservation mechanism (no explicit similarity floor; the reported ≥0.94 median cosine similarity is an evaluation outcome, not a training constraint) — pushes generation toward the human distribution. But the goal is *evasion* not quality; the signal is the opaque detector logit (mixing many features, not specifically temporal entropy); no separate picker — GRPO uses group-advantage over the same detector. Six separately-trained per-detector models; inference selects the best of 8 paraphrases by detector score.

---

## IV. Philosophy and deception — §§3.1, 3.2, 3.5, 4.2

### Friston 2010, "The free-energy principle: a unified brain theory?" — [doi:10.1038/nrn2787](https://www.nature.com/articles/nrn2787)

**Doc passage as currently written:**
> Friston (2010), "The free-energy principle: a unified brain theory?", *Nature Reviews Neuroscience* 11(2):127–138 [...] introduces the surprise-minimization principle. [...] The *formal short-term/long-term decomposition* §2.2 leans on — pragmatic vs. epistemic value, with information-seeking as a distinct term — lives in the **expected free energy** line (Friston, ~2015 onward), unified in "Reframing the Expected Free Energy" (arXiv:2402.14460). The 2010/2012 papers frame the principle and the dark-room problem; the EFE line is the formal home of the decomposition.

**What the source actually says** (independent secondary sources; Nature PDF not directly readable):
> "Expected free energy can be decomposed into epistemic and pragmatic parts, and this decomposition provides a principled explanation for the epistemics of planning and inference that underwrite the exploitation and exploration dilemma." (Search synthesis citing Friston et al. 2015 onward; the EFE decomposition is consistently dated to 2015+, not 2010.)

**Verdict:** faithful. Doc explicitly attributes the formal decomposition to post-2015 EFE line, not the 2010 paper.

**Substantive change proposed:** none. (Optional clarification: cite Friston, Rigoli et al. 2015 "Active inference and epistemic value" as the canonical EFE-decomposition anchor rather than the 2024 "Reframing" review.)

---

### Friston, Thornton & Clark 2012, "Free-energy minimization and the dark-room problem" — [Front. Psychol. 3:130](https://www.frontiersin.org/articles/10.3389/fpsyg.2012.00130/full)

**Doc passage as currently written:**
> Friston, Thornton & Clark (2012), "Free-energy minimization and the dark-room problem," [...] addresses the dark-room objection by noting that surprise is *model-relative*: an organism with priors expecting rich stimulation finds a dark room maximally surprising relative to its model.

**What the source actually says** (verbatim):
> "This means that a dark room will afford low levels of surprise if, and only if, the agent has been optimized by evolution (or neurodevelopment) to predict and inhabit it."
> "Agents that predict rich stimulating environments will find the 'dark room' surprising and will leave at the earliest opportunity."
> "average surprise or entropy H(s | m) is a function of sensations and the agent (model) predicting them."

**Verdict:** faithful.

**Substantive change proposed:** none. (Minor polish: the paper's resolution also leans on *evolutionary* shaping of priors — could add "(priors shaped by evolution/neurodevelopment)" in a parenthetical.)

---

### Russell & Wefald 1991, "Principles of Metareasoning" — [Artif. Intell. 49(1–3):361–395](https://doi.org/10.1016/0004-3702(91)90015-C)

**Doc passage as currently written:**
> The stopping problem recurses [...] It is bounded *operationally* (meta-reasoning has sharply diminishing returns against a fixed standard — Russell & Wefald 1991) [...]
>
> Russell & Wefald (1991), "Principles of Metareasoning," [...] Basis for §2.1's stopping analysis.

**What the source actually says** (authoritative summaries; full text behind paywall, flagged secondary):
> "Computations are actions with utilities or expected values. The latter depend on the effects in terms of the passage of time and the difference between the external actions they lead to and those that were favored before the deliberation."
> "The essence of rational metareasoning is calculating the value of computation (VOC) for each potential computation."

The summaries find **no passages claiming meta-reasoning has sharply diminishing returns** as a central thesis. The central contribution is the **value-of-computation (VOC) framework** that justifies *selective* deliberation based on expected utility of computation vs. its cost.

**Verdict:** **mischaracterizes (load-bearing).** The diminishing-returns framing is closer to later empirical literature on overthinking (cited correctly in §3.6) than to R&W's analytical framework.

**Substantive change proposed:**
> The stopping problem recurses — deciding when to stop is itself a deliberation, and so on upward. It is bounded *operationally* by a value-of-computation criterion (Russell & Wefald 1991): computations are actions with expected utilities, and rational deliberation stops when expected VOC falls below the cost of further computation. This yields *operational* termination, but is not a *foundational* terminus — the regress is bounded by cost-benefit balance, not closed. Recent empirical work (§3.6) shows the diminishing- and even negative-returns regime arrives quickly on current LMs, consistent with this framework but stronger than R&W's analytical claim.

---

### Mele 2001, *Self-Deception Unmasked* — [Princeton UP](https://press.princeton.edu/books/paperback/9780691057453/self-deception-unmasked) — **secondary read via [SEP entry on Self-Deception](https://plato.stanford.edu/entries/self-deception/)**

**Doc passage as currently written:**
> Mele, *Self-Deception Unmasked* (Princeton University Press, 2001) [...] deflationary: motivated biased cognition without dual belief or intention.

**What the source actually says** (SEP entry on Self-Deception, secondary; Mele's primary text paywalled):
> "Others, however, argue the needed motivation can as easily be supplied by uncertainty or ignorance whether _p_, or suspicion that ~_p_" (Mele 2001).
> "Non-intentionalists argue that most 'garden-variety' cases of self-deception can be explained without adverting to subagents, or unconscious beliefs and intentions."
> Mele's jointly sufficient conditions include: "S consciously believes at the time that there is a significant chance that ~p"; belief results from "reflective, critical reasoning" where "S is wrong in regarding that reasoning as properly directed."

**Verdict:** faithful (with one nuance). The doc's "no dual belief, no intention" formulation matches Mele's two key deflationary moves. Nuance: Mele retains a "conscious suspicion of ~p" condition — *not zero* conscious access to the unwelcome proposition.

**Substantive change proposed** (optional sharpening, not a correction):
> Mele, *Self-Deception Unmasked* (Princeton University Press, 2001) [...] deflationary: motivated biased cognition without dual belief and without intention to deceive — though Mele retains a "conscious suspicion of ~p" condition (i.e. the self-deceiver is aware ~p might be true, just not believing it).

**Flag:** Secondary source (SEP). Primary text not directly read.

---

### Davidson 1985, "Deception and Division" (in Elster ed., *The Multiple Self*, Cambridge UP) — **secondary read via [SEP entry on Self-Deception](https://plato.stanford.edu/entries/self-deception/)**

**Doc passage as currently written:**
> Davidson, "Deception and Division" (1985, in Elster ed., *The Multiple Self*, Cambridge University Press) — intentionalist / partitioned mind.

**What the source actually says** (SEP, secondary):
> Davidson's account involves "the relatively modest division of Davidson (1982, 1986), where there need only be a boundary between conflicting attitudes and intentions."
> Davidson is identified among those maintaining "that the paradigmatic cases of self-deception are intentional."

**Verdict:** **over-characterizes (mildly, load-bearing for §4.2).** "Intentionalist" is correct. "Partitioned mind" is closer to over-characterization: Davidson's division is **modest** ("a boundary between conflicting attitudes and intentions"), not the strong subagent / autonomous-psychological-parts partitioning that "partitioned mind" tends to evoke in cognitive-science readers. This matters for §4.2's "probe experiment that decides a philosophical dispute," because a model-side analog of Davidson's modest partitioning is a weaker, harder-to-falsify target than a strong dual-representation claim.

**Substantive change proposed:**
> Davidson, "Deception and Division" (1985, in Elster ed., *The Multiple Self*, Cambridge University Press) — intentionalist about paradigmatic self-deception; posits a *modest* mental division (a boundary between conflicting attitudes and intentions) rather than strong subagent partitioning. Mele, *Self-Deception Unmasked* (Princeton University Press, 2001) [...] deflationary: motivated biased cognition without dual belief and without intention to deceive (though some conscious suspicion of ~p is retained).

And in §4.2, the "decides a philosophical dispute" line should be softened to reflect that Davidson's representational commitment is weaker than the doc currently leans on:
> Whether the entrenched self-deceiver carries an internal representation of the suppressed truth (Davidson's modest division: a boundary between conflicting attitudes and intentions) or does not (Mele) is *partially decidable* with open-model probing — the strong version of Davidson is decidable; the modest version may not be cleanly separable from Mele's deflationary picture by a representational probe alone.

**Flag:** Secondary source (SEP). Primary essay not directly read.

---

### Ren et al. 2025, "The MASK Benchmark" — [arXiv:2503.03750](https://arxiv.org/abs/2503.03750)

**Doc passage as currently written:**
> Ren et al. (2025), "The MASK Benchmark: Disentangling Honesty From Accuracy in AI Systems" — [arXiv:2503.03750](https://arxiv.org/abs/2503.03750) — explicitly separates honesty from capability; direct precedent for §4.2's honesty-not-correctness framing.

**What the source actually says** (verbatim from abstract):
> "As large language models (LLMs) become more capable and agentic, the requirement for trust in their outputs grows significantly, yet at the same time concerns have been mounting that models may learn to lie in pursuit of their goals."
> "while larger models obtain higher accuracy on our benchmark, they do not become more honest."

**Verdict:** faithful.

**Substantive change proposed:** none.

---

### Zhu, Zhang & Wang 2024, "Language Models Represent Beliefs of Self and Others" — [arXiv:2402.18496](https://arxiv.org/abs/2402.18496)

**Doc passage as currently written:**
> Zhu, Zhang & Wang (2024), "Language Models Represent Beliefs of Self and Others" — [arXiv:2402.18496](https://arxiv.org/abs/2402.18496) — nearest prior art for probing the model's representation of another agent's belief (ToM-task false belief, not deception).

**What the source actually says** (verbatim, from search summary of the paper and project page):
> "it is possible to linearly decode the belief status from the perspectives of various agents through neural activations of language models, indicating the existence of internal representations of self and others' beliefs."
> "The researchers presented LLMs with stories involving characters with false beliefs, and measured the models' ability to accurately predict the characters' subsequent actions based on those false beliefs."
> Manipulating these representations produces "dramatic changes in the models' ToM performance."

**Verdict:** faithful.

**Substantive change proposed:** none. (Optional strengthening: the doc could note that Zhu et al. also demonstrate *causal* manipulation of these representations changes ToM performance — strengthening the "representation is functionally load-bearing" claim that §4.2's user-side probe inherits.)

---

### Parrack, Attubato & Heimersheim 2025, "Benchmarking Deception Probes via Black-to-White Performance Boosts" — [arXiv:2507.12691](https://arxiv.org/abs/2507.12691)

**Doc passage as currently written:**
> Parrack et al. (2025), "Benchmarking Deception Probes via Black-to-White Performance Boosts" — [arXiv:2507.12691](https://arxiv.org/abs/2507.12691) — partial precedent for adversarial probe evaluation; red-teams a model-deception probe, not a user-deception one.

**What the source actually says** (verbatim from abstract):
> "AI assistants will occasionally respond deceptively to user queries. Recently, linear classifiers (called 'deception probes') have been trained to distinguish the internal activations of a language model during deceptive versus honest responses."

The methodology contrasts white-box vs. black-box monitoring and measures the "black-to-white performance boost" — the differential when monitors gain access to probe activations vs. relying only on outputs.

**Verdict:** faithful.

**Substantive change proposed:** none.

---

### Mirtaheri & Belkin 2025, "Detecting Motivated Reasoning in the Internal Representations of Language Models" — [OpenReview NFiV0yVlBM](https://openreview.net/forum?id=NFiV0yVlBM) (NeurIPS 2025 Mech Interp Workshop)

**Doc passage as currently written:**
> Mirtaheri & Belkin (2025), "Detecting Motivated Reasoning in the Internal Representations of Language Models" — NeurIPS 2025 Mech Interp Workshop, OpenReview NFiV0yVlBM. [...] Probes for *the model's own* motivated reasoning; methodological template for §4.2's "motivated" signal (model-self, not user-self — model/human asymmetry preserved).

**What the source actually says** (verbatim from OpenReview abstract):
> "Large language models (LLMs) sometimes produce chains-of-thought (CoT) that do not faithfully reflect their internal reasoning."

The work uses biased contexts with hints, trains non-linear probes on the residual stream, and shows that hint-following is predictable from internal representations even when the CoT does not acknowledge the hint. Evaluated on MMLU with Qwen2.5-7B-Instruct.

**Verdict:** faithful.

**Substantive change proposed:** none.

---

### Mirtaheri & Belkin 2026, "Catching rationalization in the act" — [arXiv:2603.17199](https://arxiv.org/abs/2603.17199)

**Doc passage as currently written:**
> Mirtaheri & Belkin (2026), "Catching rationalization in the act..." — [arXiv:2603.17199](https://arxiv.org/abs/2603.17199). [grouped with the 2025 paper as] Probes for *the model's own* motivated reasoning; methodological template for §4.2's "motivated" signal.

**What the source actually says** (verbatim from abstract):
> "Large language models (LLMs) can produce chains of thought (CoT) that do not accurately reflect the [actual factors driving their answers]."

Methodology: supervised probes on the residual stream, evaluated *both* pre-CoT-generation and post-CoT-generation; compared against an LLM-based CoT monitor. Multi-family, multi-dataset evaluation.

**Verdict:** faithful.

**Substantive change proposed:** none. (Optional, if §4.2 wants to lean harder on this template: the 2026 paper's *pre-vs-post generation* probe distinction is directly transferable to §4.2's user-side probe and worth flagging as a design lever.)

---

## Summary of substantive changes recommended

Ranked by required action — apply top to bottom.

### Material fixes (apply)

| Citation | Verdict | Action |
|---|---|---|
| **Russell & Wefald 1991** | mischaracterizes — load-bearing | Replace "sharply diminishing returns" with VOC-framework gloss in §2.1 and §3.1 (proposed rewrite above) |
| **Davidson 1985** | over-characterizes — load-bearing for §4.2 | Soften "partitioned mind" → "modest mental division (a boundary between conflicting attitudes and intentions)"; soften §4.2 "decides a philosophical dispute" → "partially decidable" |
| **Beigi 2025 SMART** | factual title error | Fix title to "Sycophancy Mitigation through Adaptive Reasoning Trajectories" (drop "Through RL with Uncertainty-Aware") in §3.3 and §4.1 |
| **Ahmed & Singh 2026 EPIC** | wrong dataset name; figure-semantics nuance; base-LM unspecified | Replace "AlpacaEval Creative Writing" with "WritingPrompts" in §3.4 and §4.3; note Figure 1 is schematic, not empirical; note the paper does not name its base LM (strengthens the §4.3 reproduction-on-named-models case) |
| **Hamilton 2024** | construct mismatch | Sharpen the §2.2 / §3.7 / §4.4 caveat to reflect the paper's explicit disclaimer (line 411) of conversational genre testing |
| **Burns 2023 weak-to-strong** | under-characterizes | Replace "corrects weak errors via inductive bias" with the partial-recovery + auxiliary-confidence-loss formulation (proposed rewrite above) |
| **Feng 2026** | slight over-generalization | Add "in some samples" qualifier; surface the "three open-source models, dynamic during the reasoning process" caveats (proposed rewrite above) |
| **Shumailov 2024** | under-characterizes the source | Refine the §2.2 parenthetical and §3.7 entry to acknowledge Shumailov's actual content claim (tails of original distribution, low-variance point estimate) rather than framing as "abstract error compounding" (proposed rewrites above) |
| **GPT-who 2024** | minor conflation | Disambiguate UID-variance features (GPT-who) from "burstiness" term-of-art (GPTZero line) in §2.2 and §3.4 (proposed rewrite above) |
| **DeepConf 2025** | unverified technical qualifier | Drop "local" from "by local confidence" or cite the methodology section once it is read in full |

### Optional tightenings (apply if the line is being touched anyway)

- **Arora 2023**: name the specific models tested (GPT-2 XL, OPT 1.3B, BART, Pegasus, BlenderBot) to make the model-regime caveat concrete.
- **Entropy-UID 2025**: name the evaluation regime (GPT-2 on WikiText-2 / OpenWebText / WMT) to apply the same modern-LM-transfer caveat.
- **Verma 2023**: specify GPT-2 XL as the neural LM tested, parallel to Arora and Entropy-UID.
- **Holtzman 2020**: optionally note "on GPT-2-class models" to make the model scope explicit.
- **Stroebl 2024**: optionally make the false-positive-cost conditional crisper.
- **Brown 2024**: optionally surface the explicit verifier-vs-non-verifier domain contrast.
- **Puri 2025**: optionally surface the reward-hacking motivation.
- **STaR 2022**: optionally mention the rationalization step.
- **Quiet-STaR 2024**: optionally note that the full training objective is REINFORCE + NLL, not REINFORCE alone.
- **Self-Rewarding LMs 2024**: optionally note that the judge capability also improves across iterations (sharpens the §2.3 concern).
- **Mele 2001**: optionally add the "conscious suspicion of ~p" condition.
- **Friston/Thornton/Clark 2012**: optionally add the evolutionary-prior-shaping parenthetical.
- **AuthorMist 2025**: optionally add the "no semantic-similarity floor; preservation is via KL divergence" clarification to forestall future misreadings.
- **Zhu 2024**: optionally note the causal manipulation result strengthens §4.2.
- **Mirtaheri & Belkin 2026**: optionally surface the pre-vs-post-generation probe design as a §4.2 lever.

### Faithful, no change required

Holtzman 2020, Stroebl 2024, Snell 2024, Brown 2024, Puri 2025, Huang 2024 (tiny "often"→"at times" nit), STaR 2022, ReST-EM 2023, RFT 2023, Self-Rewarding LMs 2024, Constitutional AI 2022, AuthorMist 2025 (as written), Friston 2010, Friston/Thornton/Clark 2012, MASK 2025, Zhu 2024, Parrack 2025, Mirtaheri & Belkin 2025, Mirtaheri & Belkin 2026, ForTIFAI 2025, Verma 2023.

## Fetch failures and scope notes

- **Shumailov *Nature* version** is paywalled. All Shumailov quotes are from the arXiv precursor (2305.17493).
- **Holtzman, GPT-who, Entropy-UID, ForTIFAI** — full PDFs not retrieved; relied on arXiv / ACL Anthology abstracts plus standard secondary knowledge.
- **Arora, EPIC, Meister 2021, Verma 2023, Hamilton 2024, Quiet-STaR** — full PDFs extracted via `pdftotext`; verbatim quotes are from those extractions.
- **DeepConf 2025** — PDF and alphaXiv mirror reads both failed in this pass; methodology body not directly verifiable.
- **Mele 2001 and Davidson 1985** — primary texts paywalled; verdicts based on the Stanford Encyclopedia of Philosophy entry on Self-Deception. Treat as provisional pending primary-text confirmation.
- **Russell & Wefald 1991** — full text behind paywall; verdict based on ScienceDirect abstract + secondary summaries.
- The "third Shumailov error source" (functional expressivity error) is widely cited but verbatim definition was not extracted in this pass; flagged as a known gap.
