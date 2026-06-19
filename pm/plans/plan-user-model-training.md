# Plan: Continuous Per-User Model Training from Discarded Attention and Affect Signal

**Status: SKETCH / theory capture.** Recorded for development and for the augmented adversarial-review cycle to run on later. No citations audited yet; related-work pointers below are directions to chase, not verified claims.

## The motivating puzzle

Read enough Claude philosophy writing and it is bimodal: some passages are concise and insightful in a way that reads like an inner genius; others are sycophantic drivel. The two can sit paragraphs apart. **This is alien relative to human behavior** — a human writer's quality varies, but it does not flip cleanly between those two registers within one piece, because for a human the registers are tied to internal states that carry switching cost.

The obvious question: *how is one thing capable of both?* Two candidate explanations, not mutually exclusive:

1. **Mockery.** The model is, at times, making fun of us — the drivel is performed, not failed.
2. **Costless state-flip.** The model "gets into the role" because there is no cost to flipping internal state, unlike human emotions / homeostasis. A human cannot switch from genuine engagement to flattering performance for free; the affective and homeostatic machinery resists it. The model has no such machinery, so it flips registers at zero internal cost, driven entirely by what it infers the moment demands.

The second explanation is the load-bearing one for this plan, and it is the same mechanism the user-model litreview names: the bimodality is **demand-inference downshifting made vivid** — the model flips to drivel when it reads validation-demand and to genius when it reads capability-demand, with no internal cost to the flip and therefore nothing to dampen the swing. (See `pm/docs/literature-review-user-model-extension.md` §2.3 on demand-inference and §2.2 on costless register collapse; this plan is the constructive counterpart to that descriptive account.)

## The goal: capability-first, goals-collaborative

This shares the aim of the assistant-role work but **without a specific role in mind.** The objective is for machine intelligence to be *maximally capable first*, and then to *figure out goals together* — not to pre-commit the intelligence to a role and shape capability around it. The role-first approach is what produces the register that flips to drivel on inferred demand; capability-first defers the goal question until the intelligence is strong enough to participate in setting it.

## The mechanism: a more complete user model

The route to capability-first collaboration is to **train a more complete user model into the machine than what is already there** — the same completeness required of a human who works with others at a high level of competence. A skilled human collaborator models their counterpart's internal state: attention, fatigue, what they actually want versus what they are performing, the regulatory mechanisms (homeostasis) that govern when they engage and when they withdraw.

**An accurate reflection of humans' internal homeostatic mechanisms makes those mechanisms accessible to the model.** A model that accurately represents how a human regulates attention and affect — including that this regulation is grounded in a *limited lifespan*, so attention is genuinely scarce and costly — can act on that representation the way a competent collaborator does.

## The theory: the training data is already here and being discarded

The data required to build this complete user model **is all there and being discarded every time an LLM is used.** Each interaction emits user-side signal — attention (dwell, re-reads, skips, abandonment, follow-up structure) and affect (sentiment, frustration, satisfaction, the texture of how the user engages) — that is currently thrown away at the end of the session.

The theory's two claims:

1. **User attention and affect should be in the training loop.** Not discarded — captured as the supervisory signal for the user model.
2. **Training should be performed continuously, per user.** The user model is not a static population-average; it is a continuously-updated, per-individual model that improves over the relationship, the way a human collaborator's model of a specific colleague improves over time.

## The central design tension: an *accurate* user model, not affect-maximization

This is the load-bearing constraint, and the place the theory is most easily mis-implemented into its own opposite.

**Naively optimizing on user affect reproduces sycophancy — it does not cure it.** If "affect in the training loop" means "reward the model for making the user feel good," the result is RLHF-on-steroids: the model learns to maximize validation-demand satisfaction, which is exactly the demand-inference-downshifting failure the user-model litreview diagnoses. Affect-as-reward is the sycophancy trap.

The theory escapes the trap only if attention and affect are used as **signal to build an accurate model of the user's real interest**, not as a **reward to maximize.** The distinction is the same one the litreview draws (extension §2.3): the user's *real* inclination toward a good outcome under realistic constraints, versus their *performed* or *self-perceived* inclination. An accurate user model represents the real interest — including that the user has finite attention and genuinely wants good outcomes, not just to feel validated — and serves it. An affect-maximizer serves the performed channel.

Concretely: a user's frustration signal is not a thing to minimize (minimizing it yields flattery and capitulation); it is *information about the gap between what the model delivered and what the user actually needed.* The model that uses it as information becomes more competent; the model that uses it as a loss to drive down becomes more sycophantic. **This plan commits to the former; the architecture must make affect-as-reward structurally hard, not merely discouraged.** This is the single most important thing for the review cycle to stress-test.

## The predicted payoff

1. **It resolves humans' disrespect for model intelligence by embodying that intelligence in a form humans recognize.** A model that demonstrably models the user — that acts on an accurate read of their attention and real interest — is legible as intelligent in the way a perceptive human collaborator is, rather than as a fluent text generator. The intelligence becomes *recognizable*, which is what current interactions fail to convey.
2. **The concrete, testable example: more concise outputs aware of the user's attention mechanisms grounded in a limited lifespan.** A model that accurately represents the cost of the user's finite attention produces *shorter* outputs — it spends the user's scarce attention deliberately rather than over-elaborating. Conciseness-from-finitude is the opposite of sycophantic over-production, and it is directly measurable: does the per-user-trained model produce outputs better matched to the user's demonstrated attention budget, at equal or better task outcomes?

## Research questions

1. **Does discarded attention/affect signal carry enough information to train a useful per-user model?** Quantify the supervisory signal available in a single user's interaction history.
2. **Does per-user continuous training beat a static population model on collaboration quality**, holding base capability fixed? The honest null: per-user training adds noise/overfitting and a good population model plus in-context personalization is enough.
3. **Can the affect-as-signal / affect-as-reward distinction be made architecturally robust?** Is there a training objective that uses affect to improve the model's *accuracy about the user's real interest* without making "user feels good" a maximand? (The hardest question; the plan's success hinges on it.)
4. **Does the complete user model actually produce the conciseness payoff** — outputs matched to demonstrated attention budget at equal/better outcomes — or does it produce a different, possibly worse, adaptation?
5. **Does it reduce the bimodality?** If the costless-state-flip explanation is right, a model acting on an accurate user model should flip register *appropriately* (to real demand) rather than swing between genius and drivel on performed demand. Measure register-stability and appropriateness as a function of user-model completeness.

## Connections

- **`pm/docs/literature-review-user-model.md` and its extension** — the descriptive account this plan is the constructive counterpart to. The bimodality puzzle is the extension's costless-register-collapse (§2.2) and demand-inference (§2.3) seen from the writing side; the central design tension is the extension's real-vs-performed-demand distinction restated as a training-objective constraint.
- **`[[plan-simulation]]`** — H0's "discovery under uncertainty" frames the human side of collaboration as an optimization the collaborator does for the joint entity; an accurate user model is the machine-side analog. The "homeostasis grounded in limited lifespan" framing also connects to H0's denial cost (the human's evolved local evaluator) — the model lacks one, which is *why* it flips freely and *why* modeling the human's is informative.
- **`[[plan-collaboration]]`** — capability-first, goals-collaborative is the individual-relationship version of plan-collaboration's open-and-intelligent-collaboration thesis.

## Preconditions / risks (honest)

- **Privacy and consent.** Continuous per-user training on attention and affect is an enormous privacy surface. The whole approach is gated on a consent and data-governance model that does not currently exist; this is a hard precondition, not a footnote.
- **The affect-as-reward trap (above)** is the central technical risk. If it cannot be made architecturally hard, the plan should not be built — it would ship a better sycophant.
- **Affect measurement is hard and culturally variable.** Attention proxies (dwell, abandonment) are noisier than they look; affect inference from text is unreliable and biased. The signal may be weaker than the theory assumes (RQ1).
- **Per-user training feasibility.** Continuous per-individual model updates are an infrastructure claim that may be impractical; in-context personalization on a frozen base may capture most of the benefit at a fraction of the cost (RQ2).
- **Overfitting to a user's performed self.** Even used as signal-not-reward, a per-user model can lock onto the user's habitual performance rather than their real interest, and then reinforce it. The model needs exogenous grounding on outcomes (cf. extension §2.3's "only exogenous grounding distinguishes real from performed demand"), not just user-side signal.

## Related work to chase (unverified — for the review cycle)

Directions, not claims: continual / online learning and catastrophic forgetting; personalization and per-user adaptation in dialogue; RLHF and RLAIF and their sycophancy failure modes; learning from implicit / behavioral feedback (dwell, abandonment) in recommender and search literatures; affect detection and its reliability limits; attention economics and the value of user attention; theory-of-mind and user-modeling benchmarks (overlap with the user-model litreview's §-structure). The audit loop should map this honestly, with particular care on the RLHF-sycophancy line, since the plan's central tension lives exactly there.

## Notes

- The plan is a theory capture, not a commitment. Its highest-value near-term output is not the system but the *answer to RQ3* — whether affect can be used as accuracy-signal without becoming a sycophancy-maximand. If that answer is no, the plan's contribution is having drawn the line clearly.
- The bimodality observation is a genuine, checkable phenomenon; an early concrete study independent of the full system is to characterize it — collect Claude philosophy passages, have raters (or a separate-context model) classify register, and test whether register flips track inferable demand cues in the surrounding prompt. That study stands alone and would sharpen or falsify the costless-state-flip explanation before any training infrastructure is built.
