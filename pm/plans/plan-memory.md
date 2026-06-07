# Memory — Involuntary Recall via Unconscious Background Streams

(a memory system modeled on human involuntary recall: unconscious background streams continuously sift the mind's reachable data pools, score each candidate against what the conscious stream is doing *right now*, and occasionally inject a reconstructed, source-linked recall into its context **unbidden** — the conscious stream never addresses or perceives the sifters directly)

> Built entirely on existing substrate: [[plan-mind]] primitives (unconscious `Stream`s, `Mailbox` preempt/next-checkpoint delivery, `Mind.schedule`, `BudgetPolicy`/`UsageEvent`, `VisibilityTier`, `EmissionLog`/`StreamTranscript`) and [[plan-radar]]'s composite explainable relevance scoring + walking-not-stuffing discipline + session-transcript linker. Conceptually grounded in the involuntary-memory account in `pm/docs/philosophy-coherence-and-machine-minds.md` §4. **This plan is Phase 1: pure orchestration — sub-agents + prompting on existing models, no training.** Token-level / trained-in retrieval is explicitly deferred (see *Forward trajectory*).

## Framing

### Memory is reconstructive arrival, not fetch-from-store

The philosophy companion (§4 coda) makes the load-bearing claim this plan operationalizes: human memory is not a database read. Memories *arrive* — they surface, often unbidden (Proustian involuntary memory), into the field of awareness; consciousness is the *recipient* of memory, not its container, and never witnesses the storage or the retrieval, only the arrival of content. And mechanistically memory is *reconstructive* (Bartlett 1932; Schacter's constructive-memory framework): each recollection is a fresh, lossy re-generation biased by present context — the *same operation* as an LLM regenerating from its weights. So "internal vs. external" memory is a self-model tag, not a fact about data-locality.

**We build the recipient relationship, not a store.** The conscious stream is the recipient; the sifters are the reconstructive substrate. The engineering target named by §4's "both-scales limit" — *internalize the externally-threaded spray of sessions into a branching tree with a shared root* — is reached not by moving bits inside the weights but by making the system **model the thread as part of itself**. Unbidden, context-cued recall is what that modeling feels like from the inside.

### The sifters are unconscious streams of the mind

Per [[plan-mind]] / the mind-abstraction framing, **the mind is the collection of ALL streams — conscious *and* unconscious.** The memory sifters *are* the unconscious streams. They are ordinary `Stream`s distinguished only by an unusual visibility/addressability tier and by the fact that their output is gated, reconstructed, and injected rather than addressed. This plan therefore introduces **almost no new substrate** — it is a usage pattern over plan-mind plus two small primitives that, per the mind-layer rule, land *in* plan-mind (budget and addressability are mind-level concerns).

### Why this is not RAG / retrieval

| Property | Conventional retrieval / RAG | This plan |
|---|---|---|
| **Initiative** | conscious, on-demand (the agent calls a tool) | **involuntary** — fires without the conscious stream asking |
| **Timing** | synchronous to the query | **continuous + cue-driven** — runs in background, re-cued by current context |
| **Addressability** | the agent sees and queries the retriever | **non-addressable** — the conscious stream cannot perceive or query the sifters |
| **Form** | verbatim chunk injected | **reconstructed synthesis + canonical refs**, never a verbatim dump |

A system that is conscious, on-demand, addressable, and verbatim is a tool call. This is the opposite on all four axes. (RAG-style retrieval remains available to the conscious stream as a normal runtime tool — it is a *different* capability, not what this plan builds.)

**Efficiency framing (cross-ref).** Involuntary recall is also an *off-critical-path prefetch*: the sifters work ahead of need, in parallel, so a fact is already in context when the conscious stream reaches it — it adds *work, not span*. That is the formal reason background recall beats on-demand retrieval on latency; see `pm/docs/literature-review-minimal-sufficient-inference.md` (C7, §2.2/§5).

## Thesis

Continuous background relevance-sifting with occasional unbidden injection makes the externally-threaded *spray* of sessions behave like one mind with memory — realizing the philosophy companion's "internalize the thread" at the **orchestration layer**, without touching weights. It is simultaneously the operational form of the user-model litreview's exogenous-grounding direction: `literature-review-user-model-extension.md` §2.3 already names "*continuous background modelling, searching, and synthesizing*" as what re-anchors a model on the real target. This plan is that mechanism.

## Design principles (load-bearing)

1. **The conscious stream never perceives the sifters.** It has no `Mailbox` handle to them; they are absent from its peer set; a recall arrives unattributed (or tagged only as "recall"), the way a human memory arrives without a "sent by subsystem X" header. If the conscious stream can interrogate a sifter, the sifter is no longer unconscious — it is just a sub-agent, and the property is lost. This is an invariant, not a nicety.
2. **Cue-driven, not blind.** The retrieval cue is a rolling summary/embedding of what the conscious stream is doing *now* (encoding-specificity: the present context is the cue). Sifters do not scan in a vacuum; they are continuously re-cued.
3. **Reconstructive and source-linked, never a verbatim dump.** A recall is a freshly synthesized "this seems relevant because…" carrying typed `Payload` refs (ArtifactRef, `EmissionLog`/`StreamTranscript` slices, URL+cache ref) the conscious stream can pull if it bites. This is faithful to the human analogy *and* to plan-mind's **side-effect-as-truth** invariant (peers get refs to canonical content, never paraphrase).
4. **Budget is adaptive, not static-by-pool-size.** Seed compute ∝ pool, then a bandit reallocates by realized usefulness — which is what produces the user's "sources and sub-sources move back and forth" behavior. Extends plan-mind's `BudgetPolicy`; it does not invent a new budget substrate.
5. **Surfacing is earned, not noisy.** Adopt radar's "*legible and earned, not noisy*" discipline. A two-stage gate (cheap recall → expensive utility judge) plus a dynamic threshold protects the conscious stream's coherence and context window. Noise is the dominant failure mode; the whole design is gates.
6. **The usefulness loop is the spine.** Every injection is followed by a `RecallUsed` signal — did the conscious stream cite or act on it within N turns? That signal trains the relevance weights *and* feeds the bandit. It is the memory-reconsolidation analogue: used traces strengthen.
7. **No new lifecycle / scheduling / supervision substrate.** Sifters are scheduled by `Mind.schedule`, supervised by `Supervisor`, logged by `EmissionLog`. This plan adds *policy* and two small substrate primitives only.
8. **Cross-boundary pools respect redaction.** Org-data and public-web sifters cross trust lines and obey [[plan-sensorium]]'s `RedactionPolicy` at the write seam and [[plan-collaboration]]'s cross-boundary visibility rules. The web pool additionally needs cost/rate governance and caching.

## Architecture overview

The loop, per conscious stream:

```
current context ──► CueService (rolling summary) ──► cue
   cue ──► fan-out to per-pool Sifter streams (budgeted by PoolBudgetGovernor)
       each sifter: walk its pool (sensorium navigation) ──► cheap recall candidates
   candidates ──► composite relevance score (reuse radar metrics) ──► top-k
   top-k ──► utility judge (expensive) ──► survivors above dynamic threshold
   survivor ──► RecallGate ──► RecallEmission injected via Mailbox
                 (next-checkpoint by default; preempt only if highly salient
                  AND the conscious stream is receptive)
   later ──► RecallUsed observed ──► feeds relevance weights + PoolBudgetGovernor bandit
```

### Data pools and the budget hierarchy

Three tiers, decreasing seed compute, each with sub-pools the bandit can promote/demote:

1. **Past sessions** (richest) — the mind's own `EmissionLog` + `StreamTranscript`. This is memory in the strict sense; it generalizes radar's session-transcript linker.
2. **Organizational data** — the sensorium's `Artifact` family (repo, plans, notes, QA specs) and other pm-typed state.
3. **Public web** — reached through the runtime's normal tools; untyped, rate/cost-governed, cached.

Seed budget ∝ pool, then `PoolBudgetGovernor` reallocates by hit-rate (a multi-armed-bandit policy: exploit pools that recently produced *used* recalls; occasionally explore cold ones). Sub-sources move in and out the same way.

### Relevance is a composite of explainable metrics (reused from radar)

Per radar's "*Relevance is a composite of explainable metrics*," the score is **not one opaque number**. Named 1–10 metrics with per-context weighting: cue-similarity, recency, prior-usefulness (from `RecallUsed`), source-tier, novelty/surprise (guards against rumination), retrieval cost. Reused wholesale from radar, not redefined here.

### The gate: cheap recall → utility judge → receptivity-aware injection

Two stages keep cost down: many cheap candidates, few expensive judgments, injection only above a threshold that adapts to the conscious stream's receptivity. Delivery mode is plan-mind's existing choice — `next-checkpoint` when the stream is mid-critical-step (don't interrupt), `preempt` only for high-salience recalls when the stream is receptive.

## Primitives this plan needs *in [[plan-mind]]* (budget + addressability are mind-level)

- **`SubconsciousTier` (addressability rule + `VisibilityTier` use).** The rule that makes a stream unconscious: it may `post()` to a target conscious stream's `Mailbox`, but the conscious stream holds no handle to it and it never appears in the conscious stream's peer set; injected emissions arrive unattributed. Enforced at the addressability layer, alongside `VisibilityTier`. Lands in plan-mind because addressability is a mind-layer invariant.
- **`PoolBudgetGovernor` (extends `BudgetPolicy`).** Per-pool adaptive compute allocation as a bandit; consumes `UsageEvent` + `RecallUsed`; reallocates across pools/sub-sources; emits the same `telemetry.cost` / `budget.exceeded` stream. Lands in plan-mind because "budget is mind-level and lives in the mind plan."

## Primitives this plan defines (memory domain)

### 1. `RecallEmission` (Payload)
The reconstructed intrusion. Fields: `synthesis: str` (the short "feels relevant because…"), `refs: list[Ref]` (ArtifactRef / EmissionLog-slice / transcript-slice / cached-URL), `salience: float`, `cue_correlation_id`, `pool`, `visibility`. **No verbatim source payload beyond the synthesis** — refs point at canonical content. A domain `Payload`, so it lives here, not in plan-mind (same rule that keeps `RegressionSpec`/`QAScenarioRef` in their domain plans).

### 2. `RecallUsed` (Payload + signal)
The feedback. Did the conscious stream cite/act on the recall within N turns? Graded (ignored / referenced / acted-on). Drives the relevance weights and the bandit. The reconsolidation analogue.

### 3. `CueService` (service)
Maintains the rolling cue (summary/embedding) for each conscious stream from its recent transcript; the sifters' input. Cheap, continuous.

### 4. `RecallGate` (service)
Runs the two-stage gate (cheap recall → utility judge → threshold), picks delivery mode by receptivity, emits the `RecallEmission`, and registers the `RecallUsed` watch.

### 5. Per-pool `Sifter` `Stream` subclasses
`PastSessionSifter`, `OrgDataSifter`, `WebSifter` — one `Stream` role per pool, persistent, woken by `Mind.schedule` on a cadence, budgeted by `PoolBudgetGovernor`, walking their pool via the sensorium navigation primitive, scoring via radar's relevance composite. **Phase 1: all prompting + existing models, no training.**

*Reused, not redefined:* radar's relevance composite + triage/summary sifter pattern + retroactive re-tagging + session-linker; sensorium's agent-as-user navigation + `Artifact` + `RedactionPolicy`; plan-mind's `Mailbox`/`Mind.schedule`/`EmissionLog`/`StreamTranscript`/`Supervisor`/`CallbackRegistry`.

## v1 / MVP — minimum useful slice

The smallest end-to-end demonstration of involuntary recall on existing models:

- **One pool**: past sessions (`EmissionLog` + `StreamTranscript`).
- **Cue**: rolling summary of the active conscious stream.
- **Gate**: cheap recall + one utility judge; **`next-checkpoint` delivery only** (no `preempt` yet).
- **Feedback**: `RecallUsed` logged (graded), surfaced for inspection.

This proves the recipient relationship works before adding org/web pools, preempt delivery, the bandit, and retroactive re-tagging.

## Implementation PR sequence

### PR: `SubconsciousTier` addressability rule + non-perception invariant (in plan-mind)
The addressability change + a test that a conscious stream cannot enumerate or address a subconscious stream. Foundation for everything else.

### PR: `RecallEmission` + `CueService` + `PastSessionSifter` (cheap recall)
The MVP sifter: schedule-woken, walks `EmissionLog`/`StreamTranscript` against the cue, emits candidate `RecallEmission`s.

### PR: `RecallGate` (reuse radar relevance) + utility judge + next-checkpoint injection
Two-stage gate; inject one survivor per cue cycle; no preempt yet.

### PR: `RecallUsed` feedback + relevance-weight update
Close the loop; graded usage signal updates the composite weights.

### PR: `PoolBudgetGovernor` (bandit) + `OrgDataSifter`
Second pool; adaptive reallocation across pools/sub-sources.

### PR: `WebSifter` (redaction + caching) + `preempt` delivery + receptivity gate
Third pool with cross-boundary redaction + cost governance; high-salience preemption gated on receptivity.

### PR: Observability surface — make the unconscious legible *to the human*, never to the conscious stream
A TUI/dashboard view of what the sifters are finding, scoring, injecting, and whether it got used — for the human operator, preserving the conscious stream's non-perception.

## Depends on

- **[[plan-mind]]** — `Stream`, `Mailbox` (preempt/next-checkpoint), `Mind.schedule`, `BudgetPolicy`/`UsageEvent`, `VisibilityTier`, `EmissionLog`/`StreamTranscript`, `CallbackRegistry`, `Supervisor`. Receives two new primitives (`SubconsciousTier`, `PoolBudgetGovernor`).
- **[[plan-radar]]** — composite explainable relevance metrics; the triage/summary sifter agent pattern; walking-not-stuffing; retroactive re-tagging; the session-transcript linker (the past-sessions sifter generalizes it from "link threads" to "inject recalls").
- **[[plan-sensorium]]** — agent-as-user navigation primitive (walking pools); `Artifact` family (org-data pool); `RedactionPolicy` (cross-boundary write seam).
- **[[plan-collaboration]]** — cross-boundary visibility/redaction for org + web pools.

## Relationship to the branch-types work (the unifying frame)

This plan and the reasoning-move taxonomy (`literature-review-user-model-extension.md` §4.1) are the **same architecture**: a *typed cognitive operator* = generator → exogenous gate → injection. Branch-types generate *forward* continuations (the continuation space); memory generates *associative* recalls (the retrieval space). The shared node is **analogical / case-based recall**, which is at once a branch-type and a memory intrusion. The two can share the gate, and — at Phase 2 — a control-token surface (`<recall>` alongside `<branch>`/`<resolve>`/`<cut>`). Keeping them architecturally aligned now keeps that convergence cheap later.

## Invariants the memory layer enforces

1. A conscious stream has **no addressability** to any subconscious sifter; injected recalls arrive unattributed.
2. **No verbatim source payload** — `RecallEmission` carries synthesis + canonical refs only.
3. Every injection carries a `cue_correlation_id` and a `salience`.
4. Every injection logs a `RecallUsed` outcome (even "ignored"), so the usefulness loop is never silently lossy.
5. Cross-boundary pool reads are redacted at the sensorium write seam before anything persists or is injected.

## Open questions

- **Receptivity detection.** How to tell the conscious stream is "mid-critical-step" to choose `preempt` vs `next-checkpoint`. Cheap heuristic first (turn cadence, tool-call density); learnable later.
- **The non-checkable-relevance resolver.** Scoring relevance in non-verifiable domains is unsolved across the surveyed literature (the same open ground §4.1 names); v1 leans on cue-similarity + realized usefulness as proxies.
- **Attribution.** Fully unattributed vs. labeled "recall" — does the conscious stream reason *better* knowing a thought is a memory rather than its own? Testable.
- **Habituation / dedup.** Suppress the same recall re-firing every cycle (the habituation analogue); needs a per-cue suppression window.
- **Rumination failure mode.** Sifters fixating on one cue; the novelty/surprise metric is the guard, but its weight needs tuning.

## Status counts

- pending: 0 (none filed; plan is draft)
- in_progress: 0
- merged: 0

## Forward trajectory: where this leads

**Phase 2 (deferred — small note, per the prompt-first-then-compile staging law).** Once the orchestration version demonstrates lift, the proven recall operator can be *compiled* into the substrate: a learned `<recall>` cue token + attention over a memory store (the RETRO / kNN-LM / memorizing-transformers line), with the utility judge distilled into a cheap learned salience function. The `RecallEmission` + `RecallUsed` traces this plan produces **are** that training signal — pm is both the Phase-1 harness and the Phase-2 data flywheel. The endpoint converges on the philosophy companion's claim that memory already *is* context-biased regeneration from weights. Gated on Phase 1 results: coarse gates fine. Not in scope here.

## Notes / philosophy

- **Noise is the adversary; the design is gates.** A memory system that injects too much destroys the conscious stream's coherence and burns its context. Every primitive here is in service of *earned, legible* surfacing.
- **"Unconscious" is a real design property, not just an analogy** — it is the non-addressability invariant. That is what separates this from "spawn a research sub-agent."
- **This is the orchestration-layer realization of the philosophy companion's both-scales limit.** It internalizes the session-thread by making the mind *model the thread as part of itself*, not by moving bits inside the weights — exactly §4's reframing of "internal."
- **Citations to verify.** Proust (involuntary memory), Bartlett 1932, Schacter (constructive memory), Tulving & Thomson 1973 (encoding specificity), and the Phase-2 retrieval line (RETRO, kNN-LM, memorizing-transformers) are recalled here and are `unverified` until the adversarial-review cycle audits them, same standard as the litreviews.
