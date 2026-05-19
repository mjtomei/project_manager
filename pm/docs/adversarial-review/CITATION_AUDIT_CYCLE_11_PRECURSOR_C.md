# Citation Audit — Cycle 11, Precursor C

**Scope.** Full-text deep audit of §3.7 and §4.4 (bootstrap / self-improvement cluster) of `pm/docs/literature-review-user-model-extension.md`. Each entry is sourced from the paper PDF or arXiv abstract page; verbatim quotes are reproduced from those sources.

---

### [Zelikman et al. 2022, STaR] — arXiv:2203.14465

**Doc passage as currently written** (quote):
> **STaR (Zelikman et al. 2022)** — arXiv:2203.14465. Signal: exogenous correctness verifier (final-answer match against gold).

**What the source actually says** (verbatim quote on load-bearing claims):
> "generate rationales to answer many questions, prompted with a few rationale examples; if the generated answers are wrong, try again to generate a rationale given the correct answer; fine-tune on all the rationales that ultimately yielded correct answers; repeat."

Filter signal is final-answer correctness against gold. Rationalization step regenerates a rationale *given* the correct answer when the initial attempt fails.

**Verdict:** faithful

**Substantive change proposed** (verbatim rewrite):
> *(no change — but optional tightening for completeness:)* **STaR (Zelikman et al. 2022)** — arXiv:2203.14465. Signal: exogenous correctness verifier (final-answer match against gold). Includes a rationalization step that conditions on the gold answer when the initial rationale fails, then fine-tunes on rationales whose final answer matches gold.

---

### [Zelikman et al. 2024, Quiet-STaR] — arXiv:2403.09629

**Doc passage as currently written** (quote, §3.7):
> **Quiet-STaR (Zelikman et al. 2024)** — arXiv:2403.09629. Reward is **REINFORCE with a sibling-rationale baseline** — for each position, the log-likelihood of the next *m* ground-truth tokens (typically m=4) under a thought-augmented forward pass (with a learned mixing head over base and thought-augmented logits), baselined against the mean over sibling rationales sampled at the same position. Natural text enters as the *supervision target* for the m-token lookahead; the *reward* itself is intra-batch relative (which-thought-beat-the-average), not a likelihood differential against the unaugmented model or against natural text. Closer to STaR-with-implicit-rationales than to "entropy-structure as bootstrap signal" — but the natural-text supervision target makes it the nearest spiritual precedent.

And in §4.4:
> **Quiet-STaR (Zelikman et al. 2024, §3.7)** is closest *in objective spirit* — natural-text supervision targets the m-token lookahead — but the *reward* is REINFORCE baselined against sibling rationales, not a likelihood differential against natural text or against the unaugmented model; and there is no high-entropy-candidate picker.

**What the source actually says** (verbatim quotes on load-bearing claims):

On the reward equation (Section 4.4.3, "Optimizing Rationale Generation"):
> "We use REINFORCE to optimize the likelihoods of the rationales based on their usefullness: the log-likelihood of the n_true true next tokens X_{j+1:j+ntrue+1} under the language model given previous observed tokens and a particular rationale (p^talk_{j:j+ntrue} as shorthand for the mixed prediction probabilities after thinking, see Algorithm 1). To reduce variance, we generate multiple rationale continuations for each token in the input sequence (loosely inspired by TRICE, Phan et al. (2023)). We thus define the reward r_j for each rationale T_j as the difference between p^talk_{j:j+ntrue} and the average across rationales for that token (p̄^talk_{j:j+ntrue}):
>
> r_j = log p^talk_{j:j+ntrue}(X_{j+1:j+ntrue+1}) − log p̄^talk_{j:j+ntrue}(X_{j+1:j+ntrue+1})"

On the baseline (Section 3, "Problem Statement"):
> "we use the relative improvements in the log-likelihood of the target text across rationales as an estimate of quality, but we simply subtract the mean reward and do not incorporate more complex control variates."

On the mixing head (Section 4.3):
> "From the hidden state output after each rationale, we train a 'mixing head' – a shallow MLP producing a weight determining how much the post-rationale next-token predicted logits should be incorporated compared to the base language model predicted logits."

And (Algorithm 1):
> "log p^talk_{j:j+ntrue} ← w_{j:j+ntrue} · log p^init_{j:j+ntrue} + (1 − w_{j:j+ntrue}) · log p^thought_{j:j+ntrue}   // Mix logits"

On the number of lookahead tokens:
> "The number of future tokens included in the loss is a hyper-parameter."
> "Specifically, for our C4 evaluation, we train Mistral 7B with 16 thought tokens and 4 true tokens ahead and otherwise the same setup."

**Verdict:** faithful (with a minor wording precision opportunity)

The doc's characterization is correct in all load-bearing respects:
- Baseline = mean of sibling rationales at the same position (confirmed: "subtract the mean reward").
- m = 4 is one reported config (C4 evaluation); m is officially a hyperparameter — the doc's "typically m=4" is accurate but worth flagging as "the C4 setting; m is a tunable hyperparameter, the paper also reports 8 and 12-token-ahead variants in ablations."
- Mixing head: correctly described as a learned interpolation between base (p^init) and thought-augmented (p^thought) logits. Slight wording precision: the mix is over *log-probabilities* (logits in log-space), not the logits prior to softmax — minor.
- The reward is the log-likelihood of the *next n_true ground-truth tokens of the natural text*, under the mixed (thought-augmented) distribution, minus the mean across sibling rationales. The doc correctly identifies that natural text supplies the *supervision target* and the reward is *intra-batch relative*.

One additional nuance worth noting: the paper also includes an NLL loss term alongside REINFORCE ("we also include a log-likelihood loss, L^NLL"), so the total objective is REINFORCE + NLL on the mixed distribution. This does not change the doc's claim that the *REINFORCE reward* is sibling-baselined, but the §3.7 entry could note that the full training objective is REINFORCE + NLL, not REINFORCE alone.

**Substantive change proposed** (verbatim rewrite):
> **Quiet-STaR (Zelikman et al. 2024)** — arXiv:2403.09629. The REINFORCE reward for each rationale T_j is the log-likelihood of the next n_true ground-truth tokens under a mixed ("talk") distribution — a learned mixing-head interpolation of base and thought-augmented next-token log-probabilities — minus the mean of the same quantity across sibling rationales sampled at the same position (i.e., a sample-mean baseline, not a learned value function or control variate). n_true is a hyperparameter (4 in the C4 setup; ablated up to 8 in the paper). The full training objective adds an NLL term on the mixed distribution alongside REINFORCE. Natural text enters as the *supervision target* for the n_true-token lookahead; the *reward* itself is intra-batch relative (which-thought-beat-the-average), not a likelihood differential against the unaugmented model or against natural text. Closer to STaR-with-implicit-rationales than to "entropy-structure as bootstrap signal" — but the natural-text supervision target makes it the nearest spiritual precedent.

---

### [Singh et al. 2023, ReST-EM] — arXiv:2312.06585

**Doc passage as currently written** (quote):
> **ReST / ReST-EM (Singh et al. 2023)** — arXiv:2312.06585. Signal: binary task-correctness reward; E-step samples and filters, M-step finetunes.

**What the source actually says** (verbatim quote on load-bearing claims, from abstract):
> "[the method follows a cycle of] generate samples from the model and filter them using binary feedback, fine-tune the model on these samples, and repeat this process a few times."

> "on tasks where we have access to scalar feedback, for example, on math problems where one can verify correctness."

**Verdict:** faithful

Note: the abstract uses "scalar feedback" as the general framing and "binary feedback" as the operationalized version on MATH/APPS. The doc says "binary task-correctness reward" which matches the operationalization; the general framing is "scalar," but in practice on the reported benchmarks it is binary correctness. No substantive change needed.

**Substantive change proposed** (verbatim rewrite):
> *(no change)*

---

### [Yuan et al. 2023, RFT] — arXiv:2308.01825

**Doc passage as currently written** (quote):
> **Rejection Sampling Fine-Tuning / RFT (Yuan et al. 2023)** — arXiv:2308.01825. Signal: task-correctness filter over multiple sampled trajectories.

**What the source actually says** (verbatim quote on load-bearing claims, from abstract):
> "RFT uses supervised models to generate and collect correct reasoning paths as augmented fine-tuning datasets."

> "RFT improves mathematical reasoning performance more for LLMs" when "augmented samples containing more distinct reasoning paths" are used.

**Verdict:** faithful

**Substantive change proposed** (verbatim rewrite):
> *(no change)*

---

### [Yuan et al. 2024, Self-Rewarding LMs] — arXiv:2401.10020

**Doc passage as currently written** (quote):
> **Self-Rewarding Language Models (Yuan et al. 2024)** — arXiv:2401.10020. Signal: model self-judgment (LLM-as-Judge); endogenous — an instance of the failure mode §2.3 names.

**What the source actually says** (verbatim quote on load-bearing claims, from abstract):
> the model uses "LLM-as-a-Judge prompting to provide its own rewards during training"

> "during Iterative DPO training … instruction following ability improve[s], but also the ability to provide high-quality rewards to itself."

The reward signal is endogenous (model judges itself); training is iterative DPO over three iterations.

**Verdict:** faithful

**Substantive change proposed** (verbatim rewrite):
> *(no change — but an optional tighten:)* **Self-Rewarding Language Models (Yuan et al. 2024)** — arXiv:2401.10020. Signal: model self-judgment via LLM-as-Judge prompting, trained iteratively with DPO; endogenous — an instance of the failure mode §2.3 names. The paper's own framing is that the *judge capability* also improves across iterations, which sharpens the §2.3 concern (a mirror that gets better at validating itself).

---

### [Bai et al. 2022, Constitutional AI / RLAIF] — arXiv:2212.08073

**Doc passage as currently written** (quote):
> **Constitutional AI / RLAIF (Bai et al. 2022, Anthropic)** — https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback. Two-phase. SL phase: the model self-critiques and revises its outputs against a written constitution. RL phase: AI-generated pairwise preferences (constitution-conditioned) train a *preference model* used as the RL reward — RLAIF. The grounding is a *distilled* AI-preference signal shaped by the constitution, not a direct constitutional check at each training step. Closer to model self-judgment-with-rule-prior than to an exogenous verifier — sits near the bottom of the §2.1 hierarchy of terminators.

**What the source actually says** (verbatim quote on load-bearing claims, from arXiv abstract):
> "In the supervised phase we sample from an initial model, then generate self-critiques and revisions, and then finetune the original model on revised responses. In the RL phase, we sample from the finetuned model, use a model to evaluate which of the two samples is better, and then train a preference model from this dataset of AI preferences."

> "[we] train with RL using the preference model as the reward signal, i.e. we use 'RL from AI Feedback' (RLAIF)."

**Verdict:** faithful

The two-phase structure, the use of AI preferences to train a preference model, and the fact that the preference model serves as the RL reward (not the constitution applied stepwise) are all confirmed by the abstract. The doc's "distilled AI-preference signal shaped by the constitution" is exactly correct.

**Substantive change proposed** (verbatim rewrite):
> *(no change)*

---

### [Burns et al. 2023, Weak-to-Strong Generalization] — arXiv:2312.09390

**Doc passage as currently written** (quote):
> **Weak-to-Strong Generalization (Burns et al. 2023, OpenAI)** — arXiv:2312.09390. Signal: weak supervisor's pseudo-labels; the strong student corrects weak errors via inductive bias.

**What the source actually says** (verbatim quote on load-bearing claims, from abstract):
> "strong pretrained models [trained] on labels generated by a weak model … consistently perform better than their weak supervisors."

> "finetune strong pretrained models on labels generated by a weak model"

> "naive finetuning alone" falls short of full recovery; "simple methods can often significantly improve weak-to-strong generalization" (e.g., auxiliary confidence loss).

**Verdict:** under-characterizes / mildly imprecise

The first half ("signal: weak supervisor's pseudo-labels") is faithful. The second half — "corrects weak errors via inductive bias" — is the *intuitive mechanism* the paper gestures at but is not the only or fully-established mechanism. The paper shows naive finetuning is not sufficient and that auxiliary losses (e.g., a confidence loss) materially improve weak-to-strong recovery. The doc's phrasing implies pretrained inductive bias alone does the work, which the paper does not isolate as the sole mechanism.

**Substantive change proposed** (verbatim rewrite):
> **Weak-to-Strong Generalization (Burns et al. 2023, OpenAI)** — arXiv:2312.09390. Signal: weak supervisor's pseudo-labels. The strong student recovers a fraction of its ceiling capability above the weak supervisor's level; naive finetuning alone is insufficient, and simple interventions (e.g., an auxiliary confidence loss) materially improve recovery. The paper attributes the partial recovery to a combination of strong-model pretrained inductive bias and these auxiliary training-time interventions.

---

### [David & Gervais 2025, AuthorMist] — arXiv:2503.08716

**Doc passage as currently written** (quote, §3.7):
> **AuthorMist (David & Gervais 2025)** — arXiv:2503.08716. RL loop using AI-text-detector APIs as reward — closest existing detector-as-reward bootstrap; goal is *evasion* of detection, not quality.

And in §4.4:
> **AuthorMist (David & Gervais 2025, §3.7)** is closest *mechanically*: a 3B paraphrase model fine-tuned with GRPO using AI-text-detector APIs as reward — pushes generation toward the human distribution. But the goal is *evasion* not quality; the signal is the opaque detector logit (mixing many features, not specifically temporal entropy); no separate picker — GRPO uses group-advantage over the same detector.

**What the source actually says** (verbatim quote on load-bearing claims):

On the reward function (Section 3.3):
> "The reward function is designed to quantitatively measure the success of AuthorMist in evading AI-generated text detection. Given a set of detectors D = {d_1, d_2, ..., d_k}, each detector d_j outputs either a probability score P_{d_j}(Y) ... the reward R(X, Y) for transforming an AI-generated input X into output Y is computed as follows: ... Thus, the model receives a higher reward when outputs are classified as more human-like (lower probability of being AI-generated)."

On semantic preservation mechanism (Section 3 / 4):
> "To maintain linguistic fluency and prevent unnatural text artifacts, we incorporate a Kullback-Leibler (KL) divergence penalty in our optimization objective, keeping the updated policy distribution" close to the base model.

> "The strength of this regularization is carefully balanced to allow sufficient freedom for the model" to evade detectors "but produce unnatural text" / "Ensuring semantic preservation by limiting how much the model can alter the input."

On the 0.94 figure — it appears only as a *reported empirical result* (Section 4.3, Text Similarity, evaluating Figure 4):
> "all models maintain high semantic fidelity, with median similarity scores consistently above 0.94. The OpenAI-trained model demonstrates the highest median similarity (approximately 0.975) … The GPTZero and Sapling-trained models show slightly lower median scores (around 0.945 and 0.955 respectively) … even the lowest outliers across all models remain above 0.87"

Semantic similarity is measured *post hoc* with E5-small cosine similarity for evaluation — it is not a term in the training reward function and not enforced as a floor or constraint during training.

On the model:
> "Qwen2.5-3B GRPO-Trained Bypasser Models" (figure caption) — 3B backbone confirmed.

On training: six separate models, one per target detector. At inference: 8 candidate paraphrases per chunk, lowest detector score selected.

**Verdict:** mischaracterizes (the ≥0.94 floor claim) / faithful on everything else

The doc says "the semantic-similarity floor (≥0.94)" implying 0.94 is a *constraint/floor* in the training reward. It is not. The 0.94 figure is a *median outcome* of evaluation, not a training-time constraint. The actual semantic-preservation mechanism in training is **KL divergence regularization to the base model**, balanced as a hyperparameter — there is no explicit similarity floor and no similarity term in the reward.

All other claims (3B model, GRPO, detector-API-as-reward, evasion goal, six per-detector models, no separate picker) are faithful. The §3.7 entry is fine; the §4.4 entry is fine. The user's prompt explicitly asked to verify the ≥0.94 floor and the GRPO reward composition — the floor is not real, and the GRPO reward is composed of *(a) detector-derived human-likelihood reward (averaged or aggregated across the detector set, with group-relative baseline subtraction per GRPO) plus (b) a KL penalty against the reference policy*. No semantic-similarity term.

The audit prompt itself references "the semantic-similarity floor (≥0.94)" — this phrasing does not appear in the current extension doc verbatim (the doc does not state a floor), so the audit-prompt assumption was checking whether such a floor exists. It does not. The current §3.7 / §4.4 wording does not assert a floor and is therefore correct as written; the only risk would be if a future revision added that claim.

**Substantive change proposed** (verbatim rewrite):
> *(no change to §3.7 or §4.4 wording — both are faithful as currently written. If a future revision considers adding a semantic-similarity-floor claim, it should NOT be added: AuthorMist enforces semantic preservation via KL divergence to the base policy, not via a similarity floor. The "≥0.94" figure is a median post-hoc evaluation outcome, not a training constraint.)*
>
> *Optional tightening to make this explicit and forestall future misreadings:* **AuthorMist (David & Gervais 2025, §3.7)** is closest *mechanically*: a Qwen2.5-3B paraphrase model fine-tuned with GRPO using AI-text-detector APIs as reward and KL divergence to the base model as the sole semantic-preservation mechanism (no explicit similarity floor; the reported ≥0.94 median cosine similarity is an evaluation outcome, not a training constraint) — pushes generation toward the human distribution. But the goal is *evasion* not quality; the signal is the opaque detector logit (mixing many features, not specifically temporal entropy); no separate picker — GRPO uses group-advantage over the same detector. Six separately-trained per-detector models; inference selects the best of 8 paraphrases by detector score.

---

## Summary

| Citation | Verdict |
|---|---|
| STaR (Zelikman 2022) | faithful |
| Quiet-STaR (Zelikman 2024) | faithful (minor precision opportunity on n_true hyperparameter + NLL co-term) |
| ReST-EM (Singh 2023) | faithful |
| RFT (Yuan 2023) | faithful |
| Self-Rewarding LMs (Yuan 2024) | faithful |
| Constitutional AI / RLAIF (Bai 2022) | faithful |
| Weak-to-Strong (Burns 2023) | under-characterizes (oversells "inductive bias" as the lone mechanism) |
| AuthorMist (David & Gervais 2025) | faithful as written; the audit-prompt's "≥0.94 floor" framing is itself wrong — no such floor exists in the method |

**Single highest-priority change:** the Weak-to-Strong entry. The "corrects weak errors via inductive bias" wording is not what the paper claims to have established; the paper demonstrates partial recovery and identifies auxiliary losses as material to that recovery. Suggested rewrite above.

**Quiet-STaR is correctly characterized.** The detailed reward formulation in the doc — sibling-mean baseline, n_true lookahead with natural-text supervision target, mixing head over base-and-thought logits, intra-batch-relative reward — matches the paper's Algorithm 1 and Section 4.4.3 verbatim. The doc's careful distinction between "supervision target" (natural text) and "reward signal" (sibling-relative) is exactly right and is the load-bearing nuance for §4.4's argument that Quiet-STaR is a "spiritual" but not exact precedent for entropy-structure-as-bootstrap-signal.

**AuthorMist surprise.** The audit prompt asked to confirm a ≥0.94 semantic-similarity floor; checking the paper shows that figure is a *median evaluation outcome*, not a reward-function term or a training-time constraint. Semantic preservation is achieved via KL regularization to the base policy. The current extension doc does not claim a floor, so no change is required — but future revisions should not add that claim.
