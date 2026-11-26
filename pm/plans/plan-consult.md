# Consult — Learning Which Ways of Interacting with Other Operators Work Best

(there is **no hierarchy** and no "throw the hard tasks upward": every operator — the model itself, other models, research tasks, humans — has a high-dimensional, context-dependent profile of strengths and weaknesses, and models already beat humans at many tasks. The only tractable move is to **learn, via grounded RL, when and how to consult which operator**. Handicaps — limited attention, patience, cost — are simulated as **degradations of the operator's output, never announced**, so *considerate* interaction is learned rather than instructed.)

> Generalizes last turn's "condition on user-state as input, use standard RL" insight: the human is **one operator among many**, so this is bigger than the user-model ([[plan-66d430f]] becomes one application). It depends on a small plan-mind primitive (a unified `consult` request generalizing `AttentionRequest` + `BranchRequest`) and reuses standard RL on pm's logged interaction traces. **Phase 1 is a prompted consult policy — no training** — so it fits the refactor-first constraint; the RL-over-handicaps is Phase 2.

## Thesis

Once generation is cheap and parallel, real work routes through *interactions between operators* — the model consulting other models, spawning research, asking a human. The naive framing is a capability **hierarchy**: rank operators, send hard/important tasks "up." That framing is wrong on its face — models already outperform humans on many tasks, and even setting that aside, **strengths and weaknesses are too high-dimensional and too context-dependent for any fixed ordering**. The same operator is the right consult in one context and the wrong one in another.

So the problem is not "identify which tasks merit escalation." It is **routing/complementarity**: learn, per context, *which operator to consult, when, and how* — a peer-routing problem (the peer thesis applied to consultation), not a deference-to-a-superior problem. And because we don't have (and won't have) a theory of which operator is good for what, the only move that makes sense is to **learn it** from grounded outcomes — not hand-code a hierarchy or a task-difficulty heuristic.

## Design principles (load-bearing)

1. **No hierarchy; heterogeneous, context-dependent, high-dimensional profiles.** Reject "classify the task as hard/important enough to escalate." There is no fixed capability ordering. Each operator's strengths/weaknesses are high-dimensional and context-specific; the policy must **learn the matching** from grounded outcomes. Do not hard-code task-importance, capability-ordering, or an "up/down" direction — consultation is *lateral routing*.
2. **Handicaps are output degradations, never announced.** A limited-attention operator actually *ignores pieces of long input* and gives worse responses under overload; an impatient one goes terse or disengages after too many turns; a costly one is slow and budgeted. The consulting model is **never told** the handicap — it must learn to interact well with operators whose behavior *degrades*, which is exactly how **considerate** behavior emerges (short, clear asks; don't dump long text; respect implied patience). Announcing the handicap would teach the model to game an explicit rule instead of learning real consideration.
3. **Grounded reward, never operator-approval.** The reward is an exogenously verifiable task outcome (merged PR, passing test, correct result). The consulted operator — human or model — is a *participant/input*, **never the judge of success**; otherwise considerate-consultation degenerates into well-timed flattery (the sycophancy failure, one level up). Consulting *costs* (the operator's budget/latency/degraded effort); RL learns the value-of-computation tradeoff as a **trained** policy, not a hand-set threshold.
4. **Operator-state is an input, not a trained target.** Feed each operator's state/context *raw and rich* (history, current focus/attention, strengths observed from past interactions, recalled context from [[plan-memory]]); do **not** hand-encode "the features that matter" or train a model-of-the-operator. RL + attention pick what matters. (Directly the user-state-as-input insight; the human is one operator.)
5. **Standard RL on grounded tasks; pm's logs are the corpus.** No new reward machinery. **Offline RL on logged interaction traces** — real human+AI (and model+model) sessions toward grounded outcomes, which pm already generates (the founding-thesis data flywheel *is* the training set). Tasks require operator participation by construction.
6. **The `consult` primitive generalizes `AttentionRequest` + `BranchRequest`** (lands in [[plan-mind]]): one typed `consult(operator, ask, budget)` request carrying a cost, of which human-consult (`AttentionRequest`) and model/research-consult (`BranchRequest`, e.g. the deep-research workflow) are instances. Lateral routing, not upward escalation.
7. **Prompt-first, then compile.** Phase 1 is a *prompted* consult policy + logging grounded outcomes (no training — refactor-safe). Phase 2 is the handicap-degradation simulator + RL over the degradation space → the learned considerate policy.

## Architecture overview

```
task + context + operator-states ──► consult policy (whom? when? how?)
        ├─ no-consult: act directly
        └─ consult(operator, ask, budget) ──► operator responds (Phase-2: possibly DEGRADED, per a sampled, unannounced handicap)
                                          ──► model integrates the response ──► grounded task outcome ──► reward
   (Phase 2) sweep the handicap/degradation space across episodes ──► the policy learns considerate, context-matched interaction
```

- **Operator pool** — `{ self, cheaper models, expensive models, research tasks (deep-research), humans (live or via logs) }`, each with an *observed* state/profile (never a declared capability rank).
- **Consult policy (what's learned)** — given task + context + operator-states, decide whether/whom/how to consult. This is the routing + interaction policy; it is the thing RL trains.
- **Handicap-degradation simulator (Phase 2)** — wraps an operator (a real model, or a logged human's responses) and degrades its I/O per a *sampled, unannounced* handicap profile. Swept across RL episodes.
- **Training** — grounded RL, offline on logged traces first, online where cheap; consultation cost is real, so value-of-computation is learned, not set.

## The handicap-degradation model (Phase 2 — the considerate-by-construction part)

Handicaps are realized **as transforms on the operator's input-processing and output**, never as a signal to the consulting model:

- **Attention** — drops/skims pieces of long input; quality falls as input length/complexity rises (so the model learns to keep asks short and front-load what matters).
- **Patience** — terse, lower-effort, or disengaging after too many turns or an over-long ask.
- **Overload** — response quality degrades with concurrent load / ask density.
- **Latency & cost** — slow and budgeted (so over-consulting is penalized by the grounded reward via opportunity cost).
- **Motivation / variable effort** — stochastic effort level (some asks get a great answer, some a shrug) — the model learns robustness, not reliance.

The **degradation space is swept** during RL so the policy generalizes to *considerate* interaction across operator profiles rather than overfitting one. None of these are surfaced to the consulting model — it infers and adapts from the degraded behavior alone.

### Is the natural LLM handicap already enough? (the central ablation)

LLM attention is *itself* a natural handicap — finite context, attention dilution, lost-in-the-middle, degraded quality on long/complex input. So **plan-mind's multi-stream collaboration already exercises considerate interaction for free**: a stream consulting another stream is consulting a (mildly) handicapped operator, and the **minimal-sufficient-emission discipline** — compress what you hand a peer (`literature-review-minimal-sufficient-inference.md`) — *is* that consideration. The open question is whether that suffices, or whether deliberately training against handicapped operators is needed.

- **Baseline:** train multi-LLM collaboration (natural handicap only); measure considerate-interaction and, critically, *human-collaboration* transfer.
- **Treatment:** add the artificial degradation sweep; measure the same.
- **Hypothesis (worth betting on, per the design discussion):** treatment > baseline on *human* collaboration, because the natural LLM handicap is **too mild and differently-shaped** — huge context windows, no fatigue or patience limits, failure modes unlike a human's. A model trained only LLM↔LLM learns to exploit the partner's *mild* limits (e.g. dump 50k tokens — the LLM copes), which *fails* with a human's tight attention and patience. The degradation sweep, pushed toward the severe/human end, is what bridges the mild-LLM regime to the human regime.
- **Calibration, not blanket consideration:** the sweep spans the mild/un-handicapped end too, so the policy learns to *calibrate* consideration to each operator's inferred limits — terse with a human, expansive with a high-capacity model — rather than overfitting to "always be terse." (Principle 2: infer the degradation from behavior.)

This ablation is the cheapest high-value experiment in the plan: the baseline arm is *already most of plan-mind*, so the marginal cost is the degradation simulator plus the human-transfer measurement.

## v1 / MVP — minimum useful slice (no training)

- **Operator pool**: self + one cheaper model + one expensive model + a human (via logged sessions).
- **Policy**: a *prompted* consult policy (decide whether/whom/how to consult).
- **Task**: a coding task with a grounded, verifiable outcome (test pass / merged PR).
- **Logging**: consult-decisions, operator responses, and grounded outcomes — the RL corpus.

No degradation simulator and no RL yet — this proves the loop, exercises the `consult` primitive, and collects the grounded interaction data Phase 2 trains on.

## Implementation PR sequence

### PR: `consult` primitive (in [[plan-mind]])
Typed `consult(operator, ask, budget) -> response` generalizing `AttentionRequest` (human) and `BranchRequest` (model/research), with a cost field; lateral, not hierarchical.

### PR: operator pool + prompted consult policy + grounded-outcome logging
The Phase-1 loop and the data-collection corpus.

### PR: handicap-degradation simulator
The unannounced I/O degradations + the sweepable degradation space.

### PR: offline RL on logged traces (deferred)
Learn the routing/interaction policy from pm's grounded interaction logs.

### PR: online RL with the degradation simulator (deferred)
Considerate-by-construction: train against swept, unannounced handicaps.

### PR: evaluation
Grounded reward held across the handicap sweep; *considerateness* metrics (does the model keep asks short / respect implied patience when the operator degrades?).

## Depends on

- **[[plan-mind]]** — the `consult` primitive (generalizing `AttentionRequest`/`BranchRequest`), `BudgetPolicy` (consultation cost), `Supervisor` (the orchestrator each operator sits under).
- **[[plan-66d430f]]** — the user-state-as-input case (the human is one operator); its interpretability/probing survives as the diagnostic for *what* operator-representations the trained policy formed.
- **[[plan-self-improve]]** — the RL/training home for the outer loop.
- **[[plan-memory]]** — assembles each operator's state/context from recalled history.
- **[[plan-collaboration]]** — multi-operator interaction, cross-mind.

## Cross-references

- **`literature-review-minimal-sufficient-inference.md`** — *value of computation* (when to consult), the "use existing RL flows, no new reward" insight, and the standard-RL staging.
- **[[plan-momentum]]** — the **dual**: momentum spends *pm's* judgment to direct the *human's* attention to the right next step; this trains *the model* to spend *operators'* attention economically. Both fall out of attention-as-the-scarce-resource.
- The grounded-usefulness thread (`pm/docs/principle-coverage-audit.md`) — reward grounded, never approval; and learn-don't-hardcode (no hierarchy / task-importance baked in).

## Open questions

- **Faithful degradation models** — how realistically must attention/patience/overload be simulated for the learned consideration to transfer to real humans? Start coarse; validate against logged human behavior.
- **Operator-state representation** — raw context vs. any structure. Default raw (don't hand-encode), but the input has to be assembled (memory/ambient) cheaply.
- **Offline-RL data sufficiency** — are pm's logged human+AI traces rich/diverse enough to learn the routing policy, or is some online/simulated data required?
- **Evaluating "considerate"** — a grounded definition (did the operator's limited attention get respected *and* the task still succeed) vs. a proxy; avoid the engagement trap here too.
- **The no-hierarchy claim in practice** — is there *any* stable structure (some operators are reliably better in some contexts) the policy will discover, or is it fully context-dependent? An empirical readout, not an assumption.
- **Is the natural LLM handicap enough?** The central ablation (above): does artificial handicap-training beat natural multi-LLM collaboration on *human-collaboration* transfer? Guess: yes, because the natural handicap is too mild and mis-shaped relative to a human's.

## Status counts

- pending: 0 (none filed; plan is draft)
- in_progress: 0
- merged: 0

## Forward trajectory

The learned considerate-consult policy compiles (per prompt-first-then-compile) toward a trained routing capability in the model itself. At the capstone scale (`mind-search`, parked), **consultation is how work gets done in the mind-economy** — minds routing tasks to whichever operator's profile fits, under real attention/cost constraints. This plan is the near-term, grounded, single-model version of that routing layer.

## Notes / philosophy

- **No hierarchy is the load-bearing reframe.** Consultation is complementarity-routing among heterogeneous, context-dependent operators — the peer thesis made operational — not deference to a superior. We don't classify tasks as escalation-worthy; we learn which interactions work.
- **Handicaps-as-degradation is what makes consideration *learned, not instructed*.** Real humans don't announce "I have limited attention" — they skim and miss things. Training against operators that *actually* degrade is the only way the model learns genuine consideration rather than rule-following.
- **The dual of momentum.** Two readouts of the same scarce resource: pm directing the human's attention (momentum) and the model spending operators' attention economically (consult).
