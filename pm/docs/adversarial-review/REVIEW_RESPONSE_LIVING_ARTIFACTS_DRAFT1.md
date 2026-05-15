# Response to the living-artifacts literature review (first draft)

Date: 2026-05-15
Responding to: the first draft of `pm/docs/literature-review-living-artifacts.md` and its self-flagged "four overstatements + narrowed contribution"

The first draft did its job — it found three pieces of close prior art (CodeCRDT, SwarmSys, "Drop the Hierarchy and Roles") and honestly flagged where the plan's framing was at risk. The plan owner has given direct guidance on how to handle each. This document records those decisions and specs the edits.

## Decision 1 — keep the whole framing; the close prior art is academic, not deployed

**Guidance**: keep the plan's framing unless the close-prior-art works saw commercial or other real-world success. They didn't:

- **CodeCRDT** (arXiv:2510.18893, 2025): verified academic. A 600-trial evaluation paper; the pattern shows up-to-21.1% speedup on some tasks and up-to-39.4% slowdown on others. No commercial deployment.
- **SwarmSys** (2025): verified academic. There is no "SwarmSys" product. (Note: there *is* a commercial framework called **Swarms** — kyegomez/swarms, swarms.ai, "enterprise-grade multi-agent orchestration" — but that is a *different thing*: a central-ish orchestration framework, not the decentralized-living-artifact architecture. The lit review must not conflate the academic SwarmSys paper with the commercial Swarms framework, and should note that the commercial product in this space is orchestration-centric, which is the design the plan argues against.)
- **"Drop the Hierarchy and Roles"** (arXiv:2603.28990, 2026): a 2026 arXiv study. No deployment.

**Therefore**: the plan's framing stays whole. The first draft flagged four overstatements for correction; **do not collapse them.** Instead, restore the framing and add a "Related work — and why the plan's framing stands" treatment: cite all three works as the nearest academic neighbors, then differentiate. The differentiation is not "we did it first" — it is "the plan carries this architecture toward a general artifact substrate inside a working tool, where the prior work demonstrated it on a narrower slice (CodeCRDT: code-merge specifically; SwarmSys: a coordination architecture in isolation; 'Drop the Hierarchy': a controlled study, not a system)." Academic demonstration of an adjacent idea does not preempt building the substrate; it corroborates the direction.

This is the "narrow the contribution, don't collapse it" principle applied with the plan owner's calibration: the narrowing the first draft proposed was too aggressive. The honest residual is larger than the draft claimed — see Decision 4.

## Decision 2 — the strong-vs-weak-model finding is time-relative

**Guidance**: "Drop the Hierarchy" found self-organization is "a privilege of strong models" and that autonomy hurts weak models — the first draft flagged this as a threat to the plan's cost-stratification idea. The plan owner's response: *that distinction is relative. Whatever their strong model was will be weak within a few years at most.*

**This is correct and the lit review should state it.** The cost-stratification design does not require *today's* weak models to self-organize. It requires that, as the capability frontier rises, the capability floor for "can participate in negotiation competently" falls below the cost tier you want to staff routine tasks with. "Drop the Hierarchy"'s finding is a snapshot: at the time of that study, the self-organization floor sat above the cheap tier. The plan's bet is that the floor descends — today's frontier model is a routine cost tier within a few years (the same compute-cost trajectory that made every prior frontier model cheap). The plan's privileged-participant safety net (humans, watchers, integrity-maintenance tasks) is what carries the design through the interim, while the floor is still descending.

**Edit**: in §5 (self-organizing coordination) and wherever the cost-stratification idea is discussed, add the time-relativity rebuttal explicitly. Frame: "Drop the Hierarchy's strong-model-privilege finding is a snapshot of a moving floor; the plan's cost-stratification does not assume cheap models self-organize today, only that the self-organization floor descends as the frontier rises — and the privileged-participant safety net covers the interim." Do NOT present the finding as an unanswered threat.

## Decision 3 — evolutionary-algorithms-for-prompts is not claimed as novel

**Guidance**: the plan owner did not expect EA-for-building-prompts to be new (Promptbreeder, FunSearch, AlphaEvolve, ADAS all exist), but it stays as part of the long-term plan.

**Edit**: in §6 (evolutionary computation), drop any framing that treats the plan's EA direction as novel. Cite Promptbreeder, FunSearch, AlphaEvolve, ADAS as the established prior work. Keep the plan's EA direction as a *long-term direction the substrate enables*, explicitly inheriting from this prior work. The one genuinely-unclaimed sliver the first draft identified — *negotiated internal selection* (selection emerging from the units' own negotiation rather than an external fitness function) — stays as the narrow novel element, but it is a long-term stretch direction, not a headline contribution. Don't oversell it.

## Decision 4 — restate the core contribution: the data structure

**Guidance (the plan owner's framing of the main claim)**: *"The main claim is that we need a new data structure for artifacts that is non-deterministic, relational, and relies on intelligence to resolve conflicts between edits or themselves and other artifacts — something similar to what people have likely said in the past but newly enabled by LLMs."*

This is the contribution statement the lit review's conclusion should be built around. Unpack it:

- **A new data structure for artifacts.** Not a coordination protocol, not an agent architecture — a *data structure*. The plan's "what the artifact looks like" section (document body + live task queue + negotiation history + self-maintenance schedule + rejection log) is the structure. The contribution is specifying and building it.
- **Non-deterministic.** Unlike a markdown file or a database row, the artifact's state is not a fixed value — it includes proposals in superposition, converging through negotiation. The data structure has to represent in-flight, not-yet-resolved state as first-class.
- **Relational.** Artifacts negotiate with each other and with the tasks acting on them; the structure carries the relations (negotiation history, cross-artifact references, want-dependencies), not just the content.
- **Relies on intelligence to resolve conflicts.** Conflicts — between two edits, or between an artifact and itself, or between an artifact and another artifact — are resolved by LLM reasoning over the integrity constraint, not by a deterministic merge rule or a central arbiter. This is the part that was impossible before: a non-deterministic relational structure whose conflict-resolution is *intelligent* requires the intelligence to be cheap and ubiquitous enough to sit inside the structure.
- **Similar to past visions, newly enabled.** The honest framing the plan owner wants: people have gestured at active/living data before (Engelbart's NLS, blackboard systems, the actor model, Linda tuple spaces all have a piece of it). The plan does not claim the *vision* is unprecedented. It claims the *enabler* is new — LLMs make intelligent conflict resolution cheap enough to build the data structure the prior visions couldn't. The contribution is building it now that the enabler exists.

**Edit — the conclusion**: rebuild the conclusion around this contribution statement. The structure: (a) the vision is old — name the prior visions honestly (Engelbart, blackboard, actor model, Linda); (b) the prior visions were blocked because their "intelligence" had to be deterministic and programmed — name that constraint; (c) LLMs remove the constraint — intelligent conflict resolution becomes a primitive you can put inside a data structure; (d) the plan's contribution is specifying and building that data structure — non-deterministic, relational, intelligence-resolved — and proving it on a real substrate (pm's plans, then PRs, then pm itself). The close prior art (CodeCRDT, SwarmSys, Drop-the-Hierarchy) corroborates the direction on narrower slices; it does not build the general artifact data structure.

This residual is larger and more defensible than the first draft's narrowed version. The draft narrowed to four small items; the real contribution is the data structure itself, honestly positioned as an old vision newly buildable.

## Decision 5 — CodeCRDT's semantic-conflict finding is supporting evidence, not a threat

The first draft noted CodeCRDT empirically shows CRDTs leave 5-10% semantic conflicts. The first draft framed this ambiguously. **Reframe it as supporting evidence**: CodeCRDT independently demonstrates the exact gap the plan's intelligence-resolved layer fills. A CRDT gives you syntactic merge; the 5-10% residual is semantic and needs intelligence. That is the plan's thesis, corroborated by a separate group's measurement. Cite it as the empirical motivation for "relies on intelligence to resolve conflicts," not as prior art that preempts.

## Edits checklist

1. **Keep the framing.** Restore the four flagged overstatements as the plan's framing; do not collapse them. Add a "Related work — and why the framing stands" treatment.
2. Cite CodeCRDT, SwarmSys, "Drop the Hierarchy" as the nearest academic neighbors; differentiate (academic demonstration on narrower slices vs. the plan's general artifact substrate in a working tool). Note none saw commercial/real-world deployment.
3. Distinguish the academic **SwarmSys** paper from the commercial **Swarms** framework (kyegomez/swarms) — and note the commercial product is orchestration-centric, the design the plan argues against.
4. Add the strong-vs-weak time-relativity rebuttal to §5 / the cost-stratification discussion. The self-organization floor descends as the frontier rises; the privileged-participant safety net covers the interim. Not an unanswered threat.
5. §6: drop any EA-novelty framing; cite Promptbreeder / FunSearch / AlphaEvolve / ADAS as established prior work; keep the plan's EA direction as a long-term substrate-enabled direction; "negotiated internal selection" stays as a narrow long-term sliver, not oversold.
6. Reframe CodeCRDT's 5-10% semantic-conflict finding as supporting evidence for "relies on intelligence to resolve conflicts," not as preempting prior art.
7. Rebuild the conclusion around the core contribution statement: a new data structure for artifacts — non-deterministic, relational, intelligence-resolved — an old vision (Engelbart, blackboard, actor model, Linda) newly buildable because LLMs make intelligent conflict resolution a cheap primitive.

## Note for the adversarial-review loop

This is feedback on the first draft, not a formal adversarial-review cycle. After these edits land, the living-artifacts lit review enters the same loop the other two went through: Cycle 1 (fresh blind reviewer, Block 1-4, citation-graph walk), response, edits, repeat. The plan owner's calibration here — keep the framing, narrow only where prior art genuinely deployed, restate the core contribution as the data structure — is the standing guidance the loop's response cycles should apply.
