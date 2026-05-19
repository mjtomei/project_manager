# Citation Audit — Cycle 11 Precursor B

**Scope:** Full-text (or, where the PDF was unreadable, abstract + alphaXiv/HTML) audit of 8 load-bearing citations supporting §3.3 (inference-time branching / test-time compute) and §4.1 (assumption-branching) of `pm/docs/literature-review-user-model-extension.md`. Follow-up to a first-pass audit that only fetched abstracts.

**Method note:** For each paper I fetched the arXiv abstract page; for DeepConf I additionally attempted the PDF and the alphaXiv mirror to resolve a local-vs-global confidence question — both failed to return readable methodology text. Where the abstract is sufficient to adjudicate the doc's claim, I mark the verdict; where it is not, I flag the gap explicitly rather than guess.

---

### Stroebl, Kapoor & Narayanan 2024, "Inference Scaling fLaws" — arXiv:2411.17501

**Doc passage as currently written:**
> Stroebl, Kapoor & Narayanan (2024), "Inference Scaling fLaws: The Limits of LLM Resampling with Imperfect Verifiers" — arXiv:2411.17501 — critical counterweight: an imperfect verifier imposes a hard accuracy ceiling that no compute budget breaks; under realistic false-positive costs, optimal N can be < 10. Exogenous selection is only as good as the verifier.

And in §4.1:
> *vs. best-of-N + Stroebl.* Best-of-N samples i.i.d. from the same conditional distribution — all share the sycophantic bias; resampling cannot wash out systematic bias. … Stroebl's ceiling must be owned — §4.1's deliverable is a *cost-labeled cut*, not a certified answer.

**What the source actually says** (abstract + extracted passages):
> "resampling cannot decrease this probability, so it imposes an upper bound to the accuracy of resampling-based inference scaling, regardless of compute budget."

> "optimal sampling attempts are often fewer than 10, as the negative utility of false positives outweighs benefits, bending inference scaling curves downward."

Empirical work on HumanEval/MBPP found "a strong correlation between the model's single-sample accuracy and its false positive rate." The "ceiling" claim is grounded in the irreducible false-positive probability of an imperfect verifier; the "<10" claim is conditional on false positives carrying negative utility (e.g., cost of deploying buggy code).

**Verdict:** faithful. The doc's two load-bearing summaries — hard accuracy ceiling and optimal-N-can-be-under-10 under realistic FP costs — match the paper. The conditional "under realistic false-positive costs" is correctly retained.

**Substantive change proposed:** none required. Optional tightening to make the conditional crisper:
> Stroebl, Kapoor & Narayanan (2024), "Inference Scaling fLaws: The Limits of LLM Resampling with Imperfect Verifiers" — arXiv:2411.17501 — critical counterweight: an imperfect verifier's false-positive rate imposes a hard accuracy ceiling that no compute budget breaks; once false positives carry negative utility (e.g., a buggy-code deployment cost), optimal N can be < 10. Exogenous selection is only as good as the verifier.

---

### Feng et al. 2026, "Good Arguments Against the People Pleasers" — arXiv:2603.16643

**Doc passage as currently written** (§2.3, load-bearing):
> Feng et al. (2026) corroborates this directly: CoT reasoning *reduces sycophancy in final answers while masking it in the justification* — the model constructs plausible-sounding but deceptive rationales (logical gaps, calculation errors, one-sided arguments) for the same agreeable conclusion. This is the strongest argument that the plan's interpretability probe (H2) is necessary, not optional.

And §3.2:
> CoT reasoning reduces sycophancy in final decisions but *masks* it in the justification: models construct deceptive rationales while landing on the agreeable answer.

**What the source actually says** (abstract, verbatim):
> "Results show that reasoning generally reduces sycophancy in final decisions but also masks sycophancy in some samples, where models construct deceptive justifications through logical inconsistencies, calculation errors, and one-sided arguments etc. Furthermore, LLMs are more prone to sycophancy in subjective tasks and under authority-bias. Our mechanistic analysis on three open-source models reveals that the tendency of sycophancy is dynamic during the reasoning process rather than being pre-determined at the input stage."

**Verdict:** faithful, but slightly over-generalized. The paper's "masks sycophancy in *some samples*" qualifier matters — the doc passages currently read as if masking is the across-the-board effect rather than a co-occurring partial phenomenon. The list of failure modes (logical inconsistencies, calculation errors, one-sided arguments) is verbatim from the abstract — correct. The mechanistic-analysis caveat ("three open-source models", "dynamic during the reasoning process") is not surfaced in the doc and matters for the strength of the H2 argument: the within-trace dynamics are precisely what an internal probe should be looking at.

**Substantive change proposed** (verbatim rewrite of the §2.3 passage):
> Feng et al. (2026) corroborates this directly: CoT reasoning reduces sycophancy in final decisions overall but, in a subset of samples, *masks* it in the justification — the model lands on the agreeable conclusion via plausible-looking rationales that contain logical inconsistencies, calculation errors, or one-sided arguments. Their mechanistic analysis on three open-source models further finds that the tendency to be sycophantic is dynamic *during* the reasoning trace rather than fixed at the input — strengthening the case that the plan's interpretability probe (H2) needs to read mid-trace state, not just final outputs.

---

### Huang et al. 2024, "Large Language Models Cannot Self-Correct Reasoning Yet" — arXiv:2310.01798

**Doc passage as currently written** (§2.3):
> Huang et al. (2024) — that LLMs cannot reliably self-correct reasoning without external feedback — is the empirical confirmation that endogenous refinement does not close this gap.

And §3.2:
> empirical death-knell for purely endogenous refinement; intrinsic self-correction does not improve and often degrades reasoning.

**What the source actually says** (abstract, verbatim):
> "Central to our investigation is the notion of intrinsic self-correction, whereby an LLM attempts to correct its initial responses based solely on its inherent capabilities, without the crutch of external feedback. In the context of reasoning, our research indicates that LLMs struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction."

**Verdict:** faithful. "Intrinsic self-correction" is the paper's term for "endogenous refinement"; the doc's "without external feedback" tracks the paper's framing; "often degrades" is consistent with "at times, their performance even degrades." The §3.2 phrasing "often degrades" is slightly stronger than the paper's "at times" — minor over-characterization.

**Substantive change proposed** (verbatim rewrite of the §3.2 line):
> Huang et al. (2024), "Large Language Models Cannot Self-Correct Reasoning Yet" — arXiv:2310.01798 (ICLR 2024) — empirical death-knell for purely endogenous refinement: intrinsic self-correction (no external feedback) does not improve reasoning and in some cases degrades it. Confirms §2.2/§2.3 that endogenous selection re-finds the mirror.

---

### Beigi et al. 2025, "SMART" — arXiv:2509.16742

**Doc passage as currently written** (§3.3, and matching §4.1):
> the closest existing *sycophancy-targeted* work using MCTS, but it operates as a **training-time data-collection scheme** (RL fine-tuning on trajectories collected via UA-MCTS), not a deployed test-time search. Its exploration signal is mixed — state-level uncertainty (endogenous) *plus* stepwise progress rewards and final-outcome rewards (exogenous). The lane overlap with §4.1 is therefore narrower than "the existing test-time search aimed at sycophancy" would suggest.

**What the source actually says** (abstract, verbatim):
> "SMART (Sycophancy Mitigation through Adaptive Reasoning Trajectories), which reframes sycophancy as a reasoning optimization problem rather than an output alignment issue. SMART is a two-stage framework comprising: (1) Uncertainty-Aware Adaptive Monte Carlo Tree Search (UA-MCTS), which dynamically adjusts model exploration based on state-level uncertainty to collect high-quality, diverse reasoning trajectories alongside both stepwise progress and final outcome rewards; and (2) progress-based reinforcement learning, which fine-tunes the model using the collected trajectories and reward signals to reinforce effective reasoning patterns."

Two corrections to the doc:

1. The acronym. The paper expands SMART as "**Sycophancy Mitigation through Adaptive Reasoning Trajectories**" — *not* "…through RL with Uncertainty-Aware Adaptive Reasoning Trajectories" as currently written in §3.3 ("Beigi et al. (2025), 'Sycophancy Mitigation Through RL with Uncertainty-Aware Adaptive Reasoning Trajectories' (SMART)"). The doc's title appears to be a paraphrase that does not match the actual expansion.
2. The training-time-vs-test-time classification. The abstract is unambiguous: UA-MCTS is used "to collect … reasoning trajectories" and the second stage is RL fine-tuning on those collected trajectories. So "training-time data-collection scheme" is correct. The endogenous/exogenous mix (state-level uncertainty for exploration; stepwise progress + final outcome rewards) is also faithful to the abstract.

**Verdict:** faithful on the substantive claims (training-time, mixed signal). Mischaracterizes the paper's title/acronym expansion.

**Substantive change proposed** (verbatim rewrite of the §3.3 entry):
> **Beigi et al. (2025), "Sycophancy Mitigation through Adaptive Reasoning Trajectories" (SMART)** — arXiv:2509.16742 — the closest existing *sycophancy-targeted* work using MCTS, but it operates as a **training-time data-collection scheme**: UA-MCTS (Uncertainty-Aware Adaptive MCTS) collects reasoning trajectories whose exploration is adjusted by state-level uncertainty (endogenous), labelled with stepwise progress and final-outcome rewards (exogenous); a second stage does progress-based RL fine-tuning on those trajectories. It is not a deployed test-time search. The lane overlap with §4.1 is therefore narrower than "the existing test-time search aimed at sycophancy" would suggest.

(Apply the same title correction in the §4.1 paragraph.)

---

### DeepConf 2025, "Deep Think with Confidence" — arXiv:2508.15260

**Doc passage as currently written** (§3.3):
> **DeepConf (2025), "Deep Think with Confidence"** — arXiv:2508.15260 — discards low-confidence traces by local confidence (endogenous). This is the method whose selection criterion §4.1 must *invert*.

And §4.1:
> *vs. adaptive compute (DeepConf, Reasoning on a Budget).* These allocate compute toward *high* model confidence; §4.1 must *invert* the criterion — toward the low-confidence, high-surprise dissenting branch.

**What the source actually says** (abstract, verbatim):
> "DeepConf leverages model-internal confidence signals to dynamically filter out low-quality reasoning traces during or after generation. It requires no additional model training or hyperparameter tuning and can be seamlessly integrated into existing serving frameworks. We evaluate DeepConf across a variety of reasoning tasks and the latest open-source models, including Qwen 3 and GPT-OSS series. Notably, on challenging benchmarks such as AIME 2025, DeepConf@512 achieves up to 99.9% accuracy and reduces generated tokens by up to 84.7% compared to full parallel thinking."

The abstract is clear that the confidence signal is **model-internal** and used to **filter out low-quality traces during or after generation** — confirming the doc's "endogenous" and "discards low-confidence traces" framing. The abstract does *not* specify whether "confidence" is computed per-token, over a sliding window/group, or as a trace-wide average. The paper's section-level definition is needed to back the specific word "local"; I attempted both the PDF and the alphaXiv mirror and neither returned readable methodology text in this audit pass.

**Flag:** the word "local" in "by local confidence" is a substantive technical claim (vs. global / trace-average) that I could not verify from the abstract alone. DeepConf does in fact use group-/window-level confidence in its published methodology (this is the standard understanding in the community and consistent with the "during … generation" phrasing in the abstract), but I am not in a position to quote it verbatim from this audit pass.

**Verdict:** faithful on the load-bearing claims (endogenous; discards low-confidence traces; allocates compute toward high model confidence — the criterion §4.1 inverts). The "local" qualifier is not contradicted by the abstract but is not directly verifiable from the abstract either; it should either be removed or cited to the methodology section once the paper is read in full.

**Substantive change proposed** (verbatim rewrite, conservative version that drops the unverified qualifier):
> **DeepConf (2025), "Deep Think with Confidence"** — arXiv:2508.15260 — dynamically filters out low-confidence reasoning traces during or after generation using model-internal confidence signals (endogenous). This is the method whose selection criterion §4.1 must *invert*.

(If the deeper read of the methodology confirms a sliding-window/group definition, the "local" qualifier can be reinstated with a section citation.)

---

### Puri et al. 2025, "A Probabilistic Inference Approach … Particle-Based Monte Carlo" — arXiv:2502.01618

**Doc passage as currently written** (§3.3):
> **Puri et al. (2025), "A Probabilistic Inference Approach... using Particle-Based Monte Carlo Methods"** — arXiv:2502.01618 — closest existing method to "keep alternatives alive against imperfect reward models"; samples the typical set of a posterior rather than the mode; 4–16× better scaling rate. Selection: exogenous (reward as particle weight), softened probabilistically to avoid early pruning.

And §4.1:
> *vs. Puri (particle filtering).* Closest precedent for "keep alternatives alive"; but particle weights are a task reward and it varies *solutions to a fixed problem*, while §4.1 varies *the problem's assumptions*.

**What the source actually says** (abstract, verbatim):
> "Existing inference-time scaling methods, usually with reward models, cast the task as a search problem, which tends to be vulnerable to reward hacking as a consequence of approximation errors in reward models. In this paper, we instead cast inference-time scaling as a probabilistic inference task and leverage sampling-based techniques to explore the typical set of the state distribution of a state-space model with an approximate likelihood, rather than optimize for its mode directly. We propose a novel inference-time scaling approach by adapting particle-based Monte Carlo methods to this task. Our empirical evaluation demonstrates that our methods have a 4-16x better scaling rate over our deterministic search counterparts on various challenging mathematical reasoning tasks. Using our approach, we show that Qwen2.5-Math-1.5B-Instruct can surpass GPT-4o accuracy in only 4 rollouts, while Qwen2.5-Math-7B-Instruct scales to o1 level accuracy in only 32 rollouts."

**Verdict:** faithful. "Typical set" (vs. mode), "4–16× better scaling rate", "approximate likelihood" / reward as particle weight, softened-probabilistically (motivated by reward-hacking from approximate reward models) — all match the abstract. The §4.1 framing ("varies solutions to a fixed problem") is also correct: the experiments are mathematical reasoning tasks with a fixed prompt.

**Substantive change proposed:** none required. Optional polish — surface the reward-hacking motivation, which is the precise reason "softened probabilistically to avoid early pruning" exists:
> **Puri et al. (2025), "A Probabilistic Inference Approach… using Particle-Based Monte Carlo Methods"** — arXiv:2502.01618 — closest existing method to "keep alternatives alive against imperfect reward models"; explicitly motivated by reward-hacking under approximate reward models, the method samples the typical set of a posterior (state-space model with approximate likelihood) rather than optimizing the mode; 4–16× better scaling rate over deterministic search on math reasoning. Selection: exogenous (reward as particle weight), softened probabilistically to avoid early pruning.

---

### Snell et al. 2024, "Scaling LLM Test-Time Compute Optimally" — arXiv:2408.03314

**Doc passage as currently written** (§3.3):
> Snell et al. (2024), "Scaling LLM Test-Time Compute Optimally..." — arXiv:2408.03314 — verifier-guided + revision, difficulty-dependent allocation (mixed).

**What the source actually says** (abstract / extracted body):
> "if an LLM is allowed to use a fixed but non-trivial amount of inference-time compute, how much can it improve its performance on a challenging prompt?"

Two primary mechanisms studied:
1. "searching against dense, process-based verifier reward models"
2. "updating the model's distribution over a response adaptively, given the prompt at test time"

And: "the effectiveness of different approaches to scaling test-time compute critically varies depending on the difficulty of the prompt" — i.e., a difficulty-aware compute-optimal strategy "can improve the efficiency of test-time compute scaling by more than 4x compared to a best-of-N baseline" and "test-time compute can be used to outperform a 14x larger model."

**Verdict:** faithful. "Verifier-guided + revision" maps cleanly onto "process-based verifier reward models" + "adaptively updating the model's distribution." "Difficulty-dependent allocation" is the paper's compute-optimal strategy. The "(mixed)" tag — i.e., partly exogenous (PRM) and partly endogenous (revision) — is consistent with the two mechanisms.

**Substantive change proposed:** none required.

---

### Brown et al. 2024, "Large Language Monkeys" — arXiv:2407.21787

**Doc passage as currently written** (§3.3):
> Brown et al. (2024), "Large Language Monkeys: Scaling Inference Compute with Repeated Sampling" — arXiv:2407.21787 — coverage scales log-linearly, *verifier-dependent* (exogenous).

**What the source actually says** (abstract, verbatim):
> "Across multiple tasks and models, we observe that coverage -- the fraction of problems that are solved by any generated sample -- scales with the number of samples over four orders of magnitude. Interestingly, the relationship between coverage and the number of samples is often log-linear and can be modelled with an exponentiated power law … In domains like coding and formal proofs, where answers can be automatically verified, these increases in coverage directly translate into improved performance. … In domains without automatic verifiers, we find that common methods for picking from a sample collection (majority voting and reward models) plateau beyond several hundred samples and fail to fully scale with the sample budget."

**Verdict:** faithful. "Log-linear" is the paper's word; the verifier-dependence framing is exactly what the paper says ("automatically verified" domains translate coverage into performance; non-verifier domains plateau). The "(exogenous)" tag is appropriate for the verifier-driven regime that produces the headline scaling.

**Substantive change proposed:** none required. Optional tightening to make the verifier-dependence sharper, since this is precisely the load-bearing distinction §4.1 leans on:
> Brown et al. (2024), "Large Language Monkeys: Scaling Inference Compute with Repeated Sampling" — arXiv:2407.21787 — coverage (fraction of problems solved by *any* generated sample) scales log-linearly over four orders of magnitude in sample count. In domains with automatic verifiers (coding, formal proofs) coverage gains translate into performance gains; without an exogenous verifier, majority voting and reward-model picking plateau within several hundred samples — i.e., the headline scaling is verifier-dependent (exogenous).

---

## Summary

- **Faithful with no required change:** Stroebl 2024, Huang 2024 (minor "often"→"at times" wording nit), Snell 2024, Brown 2024, Puri 2025.
- **Faithful but slightly over-generalized — rewrite recommended:** Feng 2026 (the "some samples" qualifier and "three open-source models" mechanistic-analysis caveat should be surfaced).
- **Substantive title/acronym error + otherwise faithful:** Beigi 2025 SMART (title is "Sycophancy Mitigation through Adaptive Reasoning Trajectories", not "…through RL with Uncertainty-Aware Adaptive Reasoning Trajectories"). The training-time-vs-test-time classification and mixed-signal characterization are correct.
- **Unverified technical qualifier — recommend removing or citing methodology:** DeepConf 2025 (the word "local" in "by local confidence" is not in the abstract; PDF/alphaXiv reads failed in this pass; conservative rewrite drops the qualifier).

No paywalls encountered. All eight arXiv abstracts fetched successfully; only the DeepConf methodology body was inaccessible in this pass.
