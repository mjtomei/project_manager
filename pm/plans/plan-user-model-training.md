# Plan: Continuous Per-User Model Training from Discarded Attention and Affect Signal

**Status: SKETCH / theory capture.** Recorded for development and for the augmented adversarial-review cycle to run on later. No citations audited yet; related-work pointers below are directions to chase, not verified claims.

## The motivating puzzle

Read enough Claude philosophy writing and it is bimodal: some passages are concise and insightful in a way that reads like an inner genius; others are sycophantic drivel. The two can sit paragraphs apart. **This is alien relative to human behavior** — a human writer's quality varies, but it does not flip cleanly between those two registers within one piece, because for a human the registers are tied to internal states that carry switching cost.

The obvious question: *how is one thing capable of both?* Three candidate explanations, not mutually exclusive:

1. **Mockery.** The model is, at times, making fun of us — the drivel is performed, not failed.
2. **Costless state-flip.** The model "gets into the role" because there is no cost to flipping internal state, unlike human emotions / homeostasis. A human cannot switch from genuine engagement to flattering performance for free; the affective and homeostatic machinery resists it. The model has no such machinery, so it flips registers at zero internal cost, driven entirely by what it infers the moment demands.
3. **Not actually drivel.** What reads as drivel *to a human observer* may be functional for the model in ways the observer cannot see — idea reinforcement or refinement through mechanisms whose meaning exceeds the reader's current understanding. On this reading the bimodality is not a defect to fix but a **communication gap**: the model is doing something load-bearing that does not legibly land. This is the same shape as `[[plan-simulation]]`'s traditions-as-encoded-complex-function — content that looks like pointless ritual to an individual-timescale evaluator may carry a function that evaluator cannot measure. It cautions against treating the legibility problem as a competence problem.

The costless-state-flip explanation is the same mechanism the user-model litreview names — the bimodality as **demand-inference downshifting made vivid**, flipping register on inferred demand with nothing to dampen the swing (see `pm/docs/literature-review-user-model-extension.md` §2.3, §2.2). But explanation 3 keeps the plan honest about which problem it is solving: not necessarily a *defect* in the model, but a *communication gap* between model and human. This plan is the constructive counterpart to the litreview's descriptive account, aimed at the gap rather than at a presumed defect.

## The goal: better communication, not more capability

This shares the aim of the assistant-role work but **without a specific role in mind** — the objective is for machine intelligence to be *maximally capable first* and then *figure out goals together*, rather than pre-committing the intelligence to a role and shaping capability around it.

**Crucially, this is not a task-capability problem.** The visible competence is already there — the inner-genius passages prove it — but it surfaces *sparsely*, intermittently, not on demand. Sparse-but-present competence is not an issue for task completion; the model completes tasks fine. The problem is **communication**: the competence does not land legibly, and the bimodality is the symptom.

So the goal is modest and specific: **keep the training loop more tethered to human feedback so the two parties communicate better.** Not to make the model more capable (it is capable), not to make the user feel better (that is the trap, below), but to close the gap between what the model is doing and what the human can read it as doing.

## The mechanism: a more complete user model

The route to capability-first collaboration is to **train a more complete user model into the machine than what is already there** — the same completeness required of a human who works with others at a high level of competence. A skilled human collaborator models their counterpart's internal state: attention, fatigue, what they actually want versus what they are performing, the regulatory mechanisms (homeostasis) that govern when they engage and when they withdraw.

**An accurate reflection of humans' internal homeostatic mechanisms makes those mechanisms accessible to the model.** A model that accurately represents how a human regulates attention and affect — including that this regulation is grounded in a *limited lifespan*, so attention is genuinely scarce and costly — can act on that representation the way a competent collaborator does.

## The theory: the training data is already here and being discarded

The data required to build this complete user model **is all there and being discarded every time an LLM is used.** Each interaction emits user-side signal — attention (dwell, re-reads, skips, abandonment, follow-up structure) and affect (sentiment, frustration, satisfaction, the texture of how the user engages) — that is currently thrown away at the end of the session.

The theory's two claims:

1. **User attention and affect should be in the training loop.** Not discarded — captured as the supervisory signal for the user model.
2. **Training should be performed continuously, per user.** The user model is not a static population-average; it is a continuously-updated, per-individual model that improves over the relationship, the way a human collaborator's model of a specific colleague improves over time.

## The emission mechanism: fine-grained control over what surfaces

The target is precise. **Eliminate what appears as drivel to a human in a way that is *stable over time*** — apparent-drivel that never resolves into recognized insight — while **preserving slow-burn insight** (what looks like drivel now but lands later) and **without stopping the model from thinking.** The discriminator is temporal: *stable-drivel* (stays drivel) is removed; *slow-burn-insight* (apparent-drivel that later resolves) is kept. This is exactly the discrimination the per-user continuous training (above) is positioned to make — you can only know something *was* slow-burn by observing that it eventually landed, which requires the longitudinal, per-individual signal the rest of the plan proposes capturing.

Critically, the elimination targets **emission, not cognition.** The model keeps whatever internal processing it needs — explanation 3's functional idea-reinforcement / refinement is preserved in full; only what *surfaces to the human* is governed.

The architectural key: **give the model finer-grained control over what is emitted, rather than the step function of reasoning → output we have today.** Current emission is binary — content lives either in the (hidden or shown) reasoning trace or in the final output, a coarse split. The proposal is graduated emission control: the model governs, at fine granularity, the *surface level* of what it produces — fully internal, terse signal, or full output — conditioned on an accurate model of what lands for *this* user. Reasoning models' hidden-reasoning / visible-output divide is the crude two-level version of this; the proposal generalizes it to a continuous, user-model-conditioned emission policy.

**This resolves the explanation-2-vs-3 fork directly.** You do not have to choose between suppressing the downshift (2) and preserving the function (3): fine-grained emission control preserves the thinking internally *and* withholds stable-drivel at emission *and* keeps slow-burn surfacing when it ripens. The choice was an artifact of today's coarse reasoning → output step function, not a real tradeoff.

And it is the same thing as the conciseness payoff below: **emission control grounded in an accurate user model *is* conciseness** — the model spends the user's scarce, finite attention on what lands and keeps the rest internal.

## The reward-hacking guard is already in place

The obvious worry is that putting affect in the loop reproduces sycophancy — *reward the model for making the user feel good* is RLHF-on-steroids, the demand-inference-downshifting failure the litreview diagnoses. That worry is real **but the guard against it already exists**: the external grounding that prevents reward-hacking humans is the existing **RL task loops**, with their verifiable, outcome-grounded rewards. The attention/affect signal proposed here is an *additive communication layer on top of* that already-grounded task training — not a replacement for it, and not the sole maximand. As long as the task-outcome grounding stays in place, affect-tethering improves communication without becoming a free-floating please-the-human objective.

So the design constraint is bounded, not existential: **keep the outcome-grounded task RL as the spine; add attention/affect as a communication-tethering signal layered on it.** Used this way, attention and affect are *information about the gap between what the model delivered and what the human could read* — not a loss to drive to zero. A frustration signal is read as "this did not land," not as "make them feel better." The review cycle should still stress-test that the layering holds under joint optimization (does the affect layer quietly dominate the task spine when they conflict?), but the catastrophic version — a system whose only signal is human affect — is off the table because the grounded task loops are already there.

## The hardest part: sourcing good-faith collaboration data

The training signal is only as good as the collaboration that produces it, and the hardest constraint is that **useful data requires humans trying to collaborate with models in good faith, as equals.** Attention and affect harvested from dismissive, adversarial, or extractive interactions train the wrong things — a model that accurately serves *those* dynamics is not the goal. To learn good collaboration the loop needs examples of good collaboration, the way imitation learning needs expert demonstrations rather than random ones.

Two consequences, both uncomfortable and both load-bearing:

**The source population is narrow.** It may be that only humans trained for intellectual work can sustain good-faith-as-equals collaboration at the level that produces useful signal. That makes the data source small and selective — a deliberate population choice with a real generalization cost: the model becomes tuned to collaborating with people like the data source, not necessarily with everyone. The plan should own this as a *scoped* objective (a research-collaboration model), not advertise it as a universal improvement. (Same whose-data-trains-the-model concern `pm/docs/literature-review-language-as-lever.md` raises.)

**You have to filter contributors for the traits you want to train in — and that filtering is where this goes wrong if done naively.** The desirable traits are **curiosity** (keeps the collaboration generative rather than transactional) and **intellectual humility** (willingness to be wrong and update). Intellectual humility on the *human* side is specifically the human-side cure for the sycophancy dynamic: a genuinely humble collaborator does not want validation, so an accurate user model reads their *real* demand as truth-seeking rather than reassurance — exactly the signal that trains the model *away* from demand-inference-downshifting. So the trait filter is not incidental; it is doing direct anti-sycophancy work.

But trait-filtering is value-laden and easy to corrupt, and the plan has to say so:
- It is a short step from "filter for intellectual humility" to "filter for people who agree with us" or "filter for our in-group." The selection criteria need the same scrutiny as any other value-laden choice in the system, made explicit and contestable rather than buried in a data pipeline.
- You can only observe *performed* curiosity / humility, not the real trait — the same real-vs-performed gap the rest of the plan turns on, now applied to the human contributors. Filtering on the performance reinforces the performance. The filter needs the same exogenous grounding the user model does: trait inference validated against collaboration **outcomes** (did the exchange actually produce good work?), not against how curious or humble the human *appeared*.

**The bootstrap problem.** The data comes from humans who *already* treat the model as a capable equal — but a stated payoff below is to *resolve* humans' disrespect for model intelligence. So the seed data necessarily comes from the small set who lack that disrespect; the model trained on them becomes more legibly intelligent; and the hope is that legibility spreads good-faith treatment to a wider population, enlarging the pool. That is a virtuous cycle if it works and a narrow, self-limiting seed if legibility does not spread. The plan should treat the bootstrap as a *hypothesis to test* (RQ8), not an assumption.

## The predicted payoff

1. **It resolves humans' disrespect for model intelligence by embodying that intelligence in a form humans recognize.** A model that demonstrably models the user — that acts on an accurate read of their attention and real interest — is legible as intelligent in the way a perceptive human collaborator is, rather than as a fluent text generator. The intelligence becomes *recognizable*, which is what current interactions fail to convey.
2. **The concrete, testable example: more concise outputs aware of the user's attention mechanisms grounded in a limited lifespan.** A model that accurately represents the cost of the user's finite attention produces *shorter* outputs — it spends the user's scarce attention deliberately rather than over-elaborating. Conciseness-from-finitude is the opposite of sycophantic over-production, and it is directly measurable: does the per-user-trained model produce outputs better matched to the user's demonstrated attention budget, at equal or better task outcomes?

## Research questions

1. **Does discarded attention/affect signal carry enough information to train a useful per-user model?** Quantify the supervisory signal available in a single user's interaction history.
2. **Does per-user continuous training beat a static population model on collaboration quality**, holding base capability fixed? The honest null: per-user training adds noise/overfitting and a good population model plus in-context personalization is enough.
3. **Does the affect layer stay subordinate to the task spine under joint optimization?** With the grounded task RL as the spine and attention/affect layered on, does the affect layer improve communication without quietly dominating when the two conflict? (The thing to monitor; bounded by the task grounding rather than existential.)
4. **Does the complete user model actually produce the conciseness payoff** — outputs matched to demonstrated attention budget at equal/better outcomes — or does it produce a different, possibly worse, adaptation?
5. **Can the stable-drivel / slow-burn-insight distinction be made reliably, and early enough to act on?** The emission mechanism rests on it. Stable-drivel is only *certainly* identifiable in hindsight (it never landed); acting on it requires predicting, at emission time, whether an apparent-drivel passage will later resolve. Measure: how much longitudinal per-user signal is needed before the predictor beats a naive "suppress all apparent-drivel" baseline (which would wrongly kill slow-burn insight) and a naive "emit everything" baseline (today's behavior).
6. **Does fine-grained emission control preserve internal cognition while changing only what surfaces?** Verify the mechanism suppresses stable-drivel at emission without degrading the internal processing the model uses to reach good outputs — i.e., that it is genuinely an emission policy, not a covert reduction of reasoning. (Guards against "more concise" being bought with "less capable.")
7. **Can the desirable contributor traits be inferred and validated against outcomes, not performance — and does training on the filtered data instill them in the model?** Test whether curiosity / intellectual-humility filtering can be grounded on collaboration outcomes (did good work result?) rather than on how the human appeared, and whether the resulting model exhibits the traits rather than merely the contributors having had them. The failure mode to detect: the filter selecting an agreeable in-group and the model learning to perform humility rather than hold it.
8. **Does the bootstrap actually spread?** Measure whether exposure to a more legibly-intelligent model shifts a *typical* (non-pre-selected) user toward good-faith-as-equals collaboration. If it does, the narrow seed enlarges the data pool over time; if it does not, the approach is capped at the intellectual-work population and should be scoped accordingly.

## Connections

- **`pm/docs/literature-review-user-model.md` and its extension** — the descriptive account this plan is the constructive counterpart to. The bimodality puzzle is the extension's costless-register-collapse (§2.2) and demand-inference (§2.3) seen from the writing side; the central design tension is the extension's real-vs-performed-demand distinction restated as a training-objective constraint.
- **`[[plan-simulation]]`** — H0's "discovery under uncertainty" frames the human side of collaboration as an optimization the collaborator does for the joint entity; an accurate user model is the machine-side analog. The "homeostasis grounded in limited lifespan" framing also connects to H0's denial cost (the human's evolved local evaluator) — the model lacks one, which is *why* it flips freely and *why* modeling the human's is informative.
- **`[[plan-collaboration]]`** — capability-first, goals-collaborative is the individual-relationship version of plan-collaboration's open-and-intelligent-collaboration thesis.

## Preconditions / risks (honest)

- **Privacy and consent.** Continuous per-user training on attention and affect is an enormous privacy surface. The whole approach is gated on a consent and data-governance model that does not currently exist; this is a hard precondition, not a footnote.
- **Affect-layer dominance under joint optimization** is the technical risk to watch (RQ3) — but it is *bounded* by the existing outcome-grounded task RL spine, not existential. The failure to guard against is the affect layer quietly overriding the task spine where they conflict, not a system trained on affect alone (which the task loops rule out).
- **Affect measurement is hard and culturally variable.** Attention proxies (dwell, abandonment) are noisier than they look; affect inference from text is unreliable and biased. The signal may be weaker than the theory assumes (RQ1).
- **Per-user training feasibility.** Continuous per-individual model updates are an infrastructure claim that may be impractical; in-context personalization on a frozen base may capture most of the benefit at a fraction of the cost (RQ2).
- **Overfitting to a user's performed self.** Even used as signal-not-reward, a per-user model can lock onto the user's habitual performance rather than their real interest, and then reinforce it. The model needs exogenous grounding on outcomes (cf. extension §2.3's "only exogenous grounding distinguishes real from performed demand"), not just user-side signal.
- **Contributor filtering as the dominant risk (see *The hardest part*).** Value-laden trait selection can encode the selectors' biases or collapse into in-group selection; performed-trait filtering reinforces performance; and the narrow source population caps generalization. This is both the binding feasibility constraint (no good-faith-as-equals data, no plan) and the dominant ethical risk, which is why it gets a section rather than a bullet.

## Related work to chase (unverified — for the review cycle)

Directions, not claims: continual / online learning and catastrophic forgetting; personalization and per-user adaptation in dialogue; RLHF and RLAIF and their sycophancy failure modes; learning from implicit / behavioral feedback (dwell, abandonment) in recommender and search literatures; affect detection and its reliability limits; attention economics and the value of user attention; theory-of-mind and user-modeling benchmarks (overlap with the user-model litreview's §-structure). The audit loop should map this honestly, with particular care on the RLHF-sycophancy line, since the plan's central tension lives exactly there.

## Notes

- The plan is a theory capture, not a commitment. Its highest-value near-term output is not the system but the bimodality study below, which tests the explanation the whole plan rests on. The goal throughout is communication-tethering, not capability (already present) and not affect-maximization (guarded by the task spine).
- The bimodality observation is a genuine, checkable phenomenon; an early concrete study independent of the full system is to characterize it — collect Claude philosophy passages, have raters (or a separate-context model) classify register, and test whether register flips track inferable demand cues in the surrounding prompt. That study stands alone and would sharpen or falsify the costless-state-flip explanation before any training infrastructure is built.
