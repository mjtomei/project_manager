# Citation Audit — Cycle 11 Precursor D

**Scope:** Deeper, full-text-read audit of load-bearing citations in §3.1, §3.2, §3.5, and §4.2 (philosophy + deception cluster) of `pm/docs/literature-review-user-model-extension.md`. Follow-up to the first-pass audit. Per-citation entries below verify whether the doc's current characterizations are faithful to source. Books are accessed via authoritative secondary summaries (SEP) and flagged as such.

---

### Friston 2010, "The free-energy principle: a unified brain theory?" — doi:10.1038/nrn2787

**Doc passage as currently written:**
> Friston (2010), "The free-energy principle: a unified brain theory?", *Nature Reviews Neuroscience* 11(2):127–138 [...] introduces the surprise-minimization principle. [...] The *formal short-term/long-term decomposition* §2.2 leans on — pragmatic vs. epistemic value, with information-seeking as a distinct term — lives in the **expected free energy** line (Friston, ~2015 onward), unified in "Reframing the Expected Free Energy" (arXiv:2402.14460). The 2010/2012 papers frame the principle and the dark-room problem; the EFE line is the formal home of the decomposition.

**What the source actually says** (verbatim, from independent secondary sources since the Nature PDF was not directly readable):
> "Expected free energy can be decomposed into epistemic and pragmatic parts, and this decomposition provides a principled explanation for the epistemics of planning and inference that underwrite the exploitation and exploration dilemma." (search synthesis citing Friston et al. 2015 onward; the EFE decomposition is consistently dated to 2015+, not 2010.)

**Verdict:** faithful. The doc explicitly attributes the formal pragmatic/epistemic decomposition to the post-2015 EFE line, not to the 2010 paper, and uses Friston 2010 only for the introduction of the surprise-minimization / free-energy principle itself. This matches the source record.

**Substantive change proposed:** none. (Optional clarification: cite Friston, Rigoli et al. 2015 "Active inference and epistemic value" as the canonical EFE-decomposition anchor rather than the 2024 "Reframing" review, which is a synthesis paper.)

---

### Friston, Thornton & Clark 2012, "Free-energy minimization and the dark-room problem" — Front. Psychol. 3:130

**Doc passage as currently written:**
> Friston, Thornton & Clark (2012), "Free-energy minimization and the dark-room problem," [...] addresses the dark-room objection by noting that surprise is *model-relative*: an organism with priors expecting rich stimulation finds a dark room maximally surprising relative to its model.

**What the source actually says** (verbatim):
> "This means that a dark room will afford low levels of surprise if, and only if, the agent has been optimized by evolution (or neurodevelopment) to predict and inhabit it."
>
> "Agents that predict rich stimulating environments will find the 'dark room' surprising and will leave at the earliest opportunity."
>
> "average surprise or entropy H(s | m) is a function of sensations and the agent (model) predicting them."

**Verdict:** faithful. The doc's characterization — surprise as model-relative, dark-room surprising relative to organisms whose priors expect rich stimulation — is exactly the paper's resolution. The doc also correctly localizes the information-seeking-as-distinct-term machinery in the later EFE line rather than here.

**Substantive change proposed:** none. (Minor polish only: the paper's resolution also leans heavily on *evolutionary* shaping of priors, which the doc could note in a parenthetical — "(priors shaped by evolution/neurodevelopment)" — but this is stylistic, not corrective.)

---

### Russell & Wefald 1991, "Principles of Metareasoning" — Artif. Intell. 49(1–3):361–395

**Doc passage as currently written:**
> The stopping problem recurses [...] It is bounded *operationally* (meta-reasoning has sharply diminishing returns against a fixed standard — Russell & Wefald 1991) [...]
>
> Russell & Wefald (1991), "Principles of Metareasoning," [...] Basis for §2.1's stopping analysis.

**What the source actually says** (verbatim, via authoritative summaries — ScienceDirect abstract + Davies summary; full text behind paywall, flagged secondary):
> "Computations are actions with utilities or expected values. The latter depend on the effects in terms of the passage of time and the difference between the external actions they lead to and those that were favored before the deliberation."
>
> "The essence of rational metareasoning is calculating the value of computation (VOC) for each potential computation."
>
> (Davies summary, on contributions): "not all computations will have the same expected utility. This non-uniformity must be learnable/predictable."

The summaries find **no passages claiming meta-reasoning has sharply diminishing returns** as a central thesis. The central contribution is the **value-of-computation (VOC) framework** that justifies *selective* deliberation based on expected utility of computation vs. its cost.

**Verdict:** mischaracterizes (load-bearing). The doc attributes a "sharply diminishing returns" claim to R&W 1991 as the operational bound on the meta-reasoning regress. R&W's actual contribution is the VOC framework: computations are actions with expected utilities, and a rational agent stops deliberating when the expected VOC drops below the cost of computation. That *yields* a stopping criterion, but the criterion is value-vs-cost balance, not a diminishing-returns law about meta-reasoning specifically. The diminishing-returns framing is closer to later empirical literature on overthinking (cited correctly in §3.6) than to R&W's analytical framework.

**Substantive change proposed:**
> The stopping problem recurses — deciding when to stop is itself a deliberation, and so on upward. It is bounded *operationally* by a value-of-computation criterion (Russell & Wefald 1991): computations are actions with expected utilities, and rational deliberation stops when expected VOC falls below the cost of further computation. This yields *operational* termination, but is not a *foundational* terminus — the regress is bounded by cost-benefit balance, not closed. Recent empirical work (§3.6) shows the diminishing- and even negative-returns regime arrives quickly on current LMs, consistent with this framework but stronger than R&W's analytical claim.

---

### Mele 2001, *Self-Deception Unmasked* (Princeton UP) — **secondary (SEP)**

**Doc passage as currently written:**
> Mele, *Self-Deception Unmasked* (Princeton University Press, 2001) [...] deflationary: motivated biased cognition without dual belief or intention.

**What the source actually says** (SEP entry on Self-Deception, secondary; Mele's primary text paywalled):
> "Others, however, argue the needed motivation can as easily be supplied by uncertainty or ignorance whether _p_, or suspicion that ~_p_" (Mele 2001).
>
> "Non-intentionalists argue that most 'garden-variety' cases of self-deception can be explained without adverting to subagents, or unconscious beliefs and intentions."
>
> Mele's jointly sufficient conditions: false belief acquired; motivationally biased treatment of relevant data; biased treatment nondeviantly causes the false belief; available data warrants ~p more than p; "S consciously believes at the time that there is a significant chance that ~p"; belief results from "reflective, critical reasoning" where "S is wrong in regarding that reasoning as properly directed."

**Verdict:** faithful (with one nuance). The doc's "no dual belief, no intention" formulation matches Mele's two key deflationary moves as SEP characterizes them. The one nuance: Mele's condition (5) — "S consciously believes there is a significant chance that ~p" — is *weaker than dual belief in p and ~p* but *not zero*: the self-deceiver retains conscious *suspicion* of ~p. The doc's "without dual belief" is correct; a strictly accurate gloss would be "without dual belief, though some conscious suspicion of the unwelcome proposition is retained."

**Substantive change proposed** (optional sharpening, not a correction):
> Mele, *Self-Deception Unmasked* (Princeton University Press, 2001) [...] deflationary: motivated biased cognition without dual belief and without intention to deceive — though Mele retains a "conscious suspicion of ~p" condition (i.e. the self-deceiver is aware ~p might be true, just not believing it).

**Flag:** Secondary source (SEP). Primary text not directly read.

---

### Davidson 1985, "Deception and Division" (in Elster ed., *The Multiple Self*) — **secondary (SEP)**

**Doc passage as currently written:**
> Davidson, "Deception and Division" (1985, in Elster ed., *The Multiple Self*, Cambridge University Press) — intentionalist / partitioned mind.

**What the source actually says** (SEP, secondary):
> Davidson's account involves "the relatively modest division of Davidson (1982, 1986), where there need only be a boundary between conflicting attitudes and intentions."
>
> Davidson is identified among those maintaining "that the paradigmatic cases of self-deception are intentional."

**Verdict:** over-characterizes (mildly, load-bearing for §4.2). The doc's "intentionalist" label is correct — SEP explicitly places Davidson among intentionalists about paradigmatic self-deception. The "partitioned mind" label is closer to over-characterization: Davidson's division is **modest** ("a boundary between conflicting attitudes and intentions"), not the strong subagent / autonomous-psychological-parts partitioning that "partitioned mind" tends to evoke in cognitive-science readers. This matters for §4.2's "probe experiment that decides a philosophical dispute," because a model-side analog of Davidson's modest partitioning is a weaker, harder-to-falsify target than a strong dual-representation claim.

**Substantive change proposed:**
> Davidson, "Deception and Division" (1985, in Elster ed., *The Multiple Self*, Cambridge University Press) — intentionalist about paradigmatic self-deception; posits a *modest* mental division (a boundary between conflicting attitudes and intentions) rather than strong subagent partitioning. Mele, *Self-Deception Unmasked* (Princeton University Press, 2001) [...] deflationary: motivated biased cognition without dual belief and without intention to deceive (though some conscious suspicion of ~p is retained).

And in §4.2, the "decides a philosophical dispute" line should be softened to reflect that Davidson's representational commitment is weaker than the doc currently leans on:
> Whether the entrenched self-deceiver carries an internal representation of the suppressed truth (Davidson's modest division: a boundary between conflicting attitudes and intentions) or does not (Mele) is *partially decidable* with open-model probing — the strong version of Davidson is decidable; the modest version may not be cleanly separable from Mele's deflationary picture by a representational probe alone.

**Flag:** Secondary source (SEP). Primary essay not directly read.

---

### Ren et al. 2025, "The MASK Benchmark" — arXiv:2503.03750

**Doc passage as currently written:**
> Ren et al. (2025), "The MASK Benchmark: Disentangling Honesty From Accuracy in AI Systems" — arXiv:2503.03750 — explicitly separates honesty from capability; direct precedent for §4.2's honesty-not-correctness framing.

**What the source actually says** (verbatim from abstract):
> "As large language models (LLMs) become more capable and agentic, the requirement for trust in their outputs grows significantly, yet at the same time concerns have been mounting that models may learn to lie in pursuit of their goals."
>
> "while larger models obtain higher accuracy on our benchmark, they do not become more honest."

The benchmark uses human-collected adversarial scenarios to measure whether LLMs lie under pressure, and explicitly contrasts truthfulness (accuracy) with honesty (non-deception).

**Verdict:** faithful. The doc's "explicitly separates honesty from capability" is exactly MASK's headline finding. The §4.2 framing precedent is accurately drawn.

**Substantive change proposed:** none.

---

### Zhu, Zhang & Wang 2024, "Language Models Represent Beliefs of Self and Others" — arXiv:2402.18496

**Doc passage as currently written:**
> Zhu, Zhang & Wang (2024), "Language Models Represent Beliefs of Self and Others" — arXiv:2402.18496 — nearest prior art for probing the model's representation of another agent's belief (ToM-task false belief, not deception).

**What the source actually says** (verbatim, from search summary of the paper and project page):
> "it is possible to linearly decode the belief status from the perspectives of various agents through neural activations of language models, indicating the existence of internal representations of self and others' beliefs."
>
> "The researchers presented LLMs with stories involving characters with false beliefs, and measured the models' ability to accurately predict the characters' subsequent actions based on those false beliefs."
>
> Manipulating these representations produces "dramatic changes in the models' ToM performance."

**Verdict:** faithful. The doc correctly identifies (a) the work probes *model representations of another agent's belief*, (b) the tasks are ToM-style false-belief tasks (not deception scenarios), and (c) the methodology is linear decoding from neural activations with causal manipulation. All three are accurately reported.

**Substantive change proposed:** none. (Optional strengthening: the doc could note that Zhu et al. also demonstrate *causal* manipulation of these representations changes ToM performance — strengthening the "representation is functionally load-bearing" claim that §4.2's user-side probe inherits.)

---

### Parrack, Attubato & Heimersheim 2025, "Benchmarking Deception Probes via Black-to-White Performance Boosts" — arXiv:2507.12691

**Doc passage as currently written:**
> Parrack et al. (2025), "Benchmarking Deception Probes via Black-to-White Performance Boosts" — arXiv:2507.12691 — partial precedent for adversarial probe evaluation; red-teams a model-deception probe, not a user-deception one.

**What the source actually says** (verbatim from abstract):
> "AI assistants will occasionally respond deceptively to user queries. Recently, linear classifiers (called 'deception probes') have been trained to distinguish the internal activations of a language model during deceptive versus honest responses."

The methodology contrasts white-box vs. black-box monitoring and measures the "black-to-white performance boost" — the differential when monitors gain access to probe activations vs. relying only on outputs.

**Verdict:** faithful. The doc correctly identifies (a) the probes red-teamed are *model-deception* probes (detecting the AI's own deception), not user-deception probes, and (b) the work is a partial precedent for adversarial probe evaluation. The "black-to-white boost" methodology nuance is not in the doc but is not load-bearing for how the citation is used.

**Substantive change proposed:** none. (Optional, for §4.2 methodological color: "the black-to-white performance boost methodology — comparing monitors with vs. without probe access — is directly applicable to §4.2's adversarial evaluation design.")

---

### Mirtaheri & Belkin 2025, "Detecting Motivated Reasoning in the Internal Representations of Language Models" — OpenReview NFiV0yVlBM (NeurIPS 2025 Mech Interp Workshop)

**Doc passage as currently written:**
> Mirtaheri & Belkin (2025), "Detecting Motivated Reasoning in the Internal Representations of Language Models" — NeurIPS 2025 Mech Interp Workshop, OpenReview NFiV0yVlBM. [...] Probes for *the model's own* motivated reasoning; methodological template for §4.2's "motivated" signal (model-self, not user-self — model/human asymmetry preserved).

**What the source actually says** (verbatim from OpenReview abstract):
> "Large language models (LLMs) sometimes produce chains-of-thought (CoT) that do not faithfully reflect their internal reasoning."

The work uses biased contexts with hints, trains non-linear probes on the residual stream, and shows that hint-following is predictable from internal representations even when the CoT does not acknowledge the hint. Evaluated on MMLU with Qwen2.5-7B-Instruct.

**Verdict:** faithful. The doc correctly identifies (a) the target is the *model's own* motivated reasoning (not the user's), (b) the methodology is internal-representation probing, and (c) the work is a methodological template for the §4.2 "motivated" signal. The model/human asymmetry framing in §4.2 is consistent with what Mirtaheri & Belkin actually study.

**Substantive change proposed:** none. (Optional precision: the doc could note the specific empirical setup — "hint-following on MMLU with non-linear residual-stream probes on Qwen2.5-7B" — for replicability, but this is methodological color not a correction.)

---

### Mirtaheri & Belkin 2026, "Catching rationalization in the act" — arXiv:2603.17199

**Doc passage as currently written:**
> Mirtaheri & Belkin (2026), "Catching rationalization in the act..." — arXiv:2603.17199. [grouped with the 2025 paper as] Probes for *the model's own* motivated reasoning; methodological template for §4.2's "motivated" signal.

**What the source actually says** (verbatim from abstract):
> "Large language models (LLMs) can produce chains of thought (CoT) that do not accurately reflect the [actual factors driving their answers]."

Methodology: supervised probes on the residual stream, evaluated *both* pre-CoT-generation and post-CoT-generation; compared against an LLM-based CoT monitor that reads the full reasoning trace. Multi-family, multi-dataset evaluation.

**Verdict:** faithful. The 2026 paper extends the 2025 workshop work to multiple model families and datasets and adds a pre-vs-post-generation probe comparison plus a CoT-monitor baseline. The doc's grouping with the 2025 paper as a single methodological template for §4.2 is accurate.

**Substantive change proposed:** none. (Optional, if §4.2 wants to lean harder on this template: the 2026 paper's *pre-vs-post generation* probe distinction is directly transferable to §4.2's user-side probe — whether the user-deception signal is present *before* the model commits to a response or only after — and worth flagging as a design lever.)

---

## Summary of Substantive Changes Recommended

| Citation | Verdict | Action |
|---|---|---|
| Friston 2010 | faithful | none |
| Friston, Thornton & Clark 2012 | faithful | none |
| Russell & Wefald 1991 | **mischaracterizes** (load-bearing) | **replace "sharply diminishing returns" with VOC-framework gloss** (§2.1 and §3.1) |
| Mele 2001 | faithful (minor nuance) | optional: add "conscious suspicion of ~p retained" clarifier |
| Davidson 1985 | **over-characterizes** (load-bearing for §4.2) | **soften "partitioned mind" to "modest mental division"; soften §4.2 "decides a philosophical dispute" claim** |
| Ren et al. 2025 (MASK) | faithful | none |
| Zhu et al. 2024 | faithful | none |
| Parrack et al. 2025 | faithful | none |
| Mirtaheri & Belkin 2025 | faithful | none |
| Mirtaheri & Belkin 2026 | faithful | none |

**Two load-bearing fixes:** (1) Russell & Wefald 1991 should be cited for its value-of-computation framework, not for a diminishing-returns claim it does not make. (2) Davidson 1985 should be characterized as proposing a *modest* mental division, not a strong partitioned mind — and §4.2's "decides a philosophical dispute" framing must be softened accordingly, because the modest version of Davidson may not be cleanly separable from Mele's deflationary picture by representational probing alone.

**Secondary-source caveat:** Mele 2001 and Davidson 1985 were accessed via the Stanford Encyclopedia of Philosophy entry on Self-Deception. The primary texts are paywalled and were not directly read; verdicts on these two should be treated as provisional pending primary-text confirmation.
