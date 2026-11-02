# Review Response — Cycle 1 (living-artifacts literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_1_LIVING_ARTIFACTS.md`

Cycle 1 reported the artifact "not converged" and surfaced four prior-art misses, two flagged as severe (MAIF, MMP). The parent agent verified all three deployment-bearing claims directly before this response was drafted — and the verification caught significant reviewer overstatement, the pattern that has held across every cycle of this loop. The response applies the "narrow the contribution; don't collapse it" principle with the plan owner's standing calibration: keep the framing unless prior art saw genuine real-world success; the core contribution is the data structure.

## Bucket A — the four prior-art finds, verified

### A1. MAIF (arXiv:2511.15097) — preempts the *vocabulary*, not the *substance*

**Verified abstract content** (verbatim quote):

> "We propose an artifact-centric AI agent paradigm where behavior is driven by persistent, verifiable data artifacts rather than ephemeral tasks... Central to this approach is the Multimodal Artifact File Format (MAIF), an AI-native container embedding semantic representations, cryptographic provenance, and granular access controls. MAIF transforms data from passive storage into active trust enforcement, making every AI operation inherently auditable. Our production-ready implementation demonstrates ultra-high-speed streaming (2,720.7 MB/s)..."

**What MAIF actually does**: MAIF is a file format for *trustworthy, auditable AI data*. Its purpose is regulatory compliance (the EU AI Act is named), provenance tracking, tamper detection, anomaly analysis. "Active trust enforcement" — the intelligence MAIF puts into the data layer is *verification and provenance*, not agency. MAIF has **no conflict-resolution mechanism, no peer-to-peer negotiation between artifacts, no "wants," no self-maintenance tasks.** "Production-ready implementation" is a throughput-benchmark claim (streaming MB/s), not a deployed-with-real-users claim — it's a 7-page paper with a GitHub repo.

**What the plan does that MAIF doesn't**: MAIF's artifacts are *auditable containers* — passive data made trustworthy. The plan's artifacts are *negotiating peers* — data made agentic. The kind of intelligence each fuses into the data layer is different: MAIF fuses verification; the plan fuses agency (wants, negotiation, self-maintenance). MAIF's artifacts don't act; they prove. The plan's artifacts act.

**Decision**: MAIF preempts the *phrase* "artifact-centric AI agent paradigm where behavior is driven by persistent data artifacts." The plan cannot claim that phrasing as novel. But MAIF does not preempt the substance — negotiation, intelligence-resolved conflict, wants. **Edit**: cite MAIF as the published precedent for the artifact-centric *framing*; differentiate explicitly — MAIF fuses verification into the data layer, the plan fuses agency. Drop any "no one has proposed artifact-centric AI" implication.

### A2. MMP — Mesh Memory Protocol (arXiv:2604.19540) — preempts the data-structure *mechanics*, not the *agency relocation*

**Verified abstract content** (verbatim quote):

> "...the Mesh Memory Protocol (MMP) specifies it. Four composable primitives work together: CAT7, a fixed seven-field schema for every Cognitive Memory Block (CMB); SVAF, which evaluates each field against the receiver's role-indexed anchors...; inter-agent lineage...; and remix, which stores only the receiver's own role-evaluated understanding of each accepted CMB... MMP is specified, shipped, and running in production across three reference deployments..."

**What MMP actually does**: MMP is a *semantic-layer protocol* for cross-session agent-to-agent collaboration. CAT7 is a typed shared-memory schema. SVAF is per-field, role-indexed *acceptance* (receiver decides field-by-field what to take from a peer). Lineage is provenance. This is genuinely close to the plan's data-structure *mechanics* — typed schema, per-field semantic evaluation, provenance, cross-session persistence.

**The crucial distinction**: MMP is a **passive shared-memory protocol**. The intelligence is in the *agents*; the memory is the *medium*. Agents read and write Cognitive Memory Blocks; agents decide what to accept. MMP's memory does not negotiate, has no agency, has no wants. The living-artifacts plan does the **inverse**: it relocates the intelligence *into the artifact*. The plan's artifact negotiates, spawns its own self-maintenance tasks, has wants. MMP keeps data and intelligence *separate* (passive memory, active agents) — which is exactly the split the plan's headline ("data + intelligence fused into a single unit") rejects.

**Deployment**: MMP claims "shipped, and running in production across three reference deployments." This is the strongest deployment claim among the four finds — stronger than MAIF, CodeCRDT, SwarmSys (all benchmark-only). But "reference deployments" reads as the authors' own reference implementations, not verified commercial third-party adoption. Per the plan owner's rule ("keep the framing unless the prior work saw commercial or other real-world success"), MMP is the closest to triggering a framing change — it is genuinely *running*. But what it runs is the passive-memory version, which is not the plan's framing.

**What the plan does that MMP doesn't** (the narrow-don't-collapse residual):
1. **Agency relocation.** MMP's memory is passive; agents hold the intelligence. The plan puts intelligence *in* the artifact — the artifact is a negotiating peer, not a medium.
2. **Artifact-spawned self-maintenance.** MMP has no notion of the memory generating its own tasks. The plan's artifacts spawn self-maintenance tasks from their own "wants."
3. **Artifact-to-artifact negotiation.** MMP is agent-to-agent *through* memory. The plan's artifacts negotiate with *each other* (the A-talks-to-Y code scenario).
4. **No central arbiter as a property of the substrate**, not just of the protocol layer.

**Replacement contribution statement** (per the methodology's procedural rule):

> "The plan's data structure is not the first typed, semantically-merged, cross-session shared memory for LLM agents — the Mesh Memory Protocol (Mesh Memory Protocol, arXiv:2604.19540) specifies and runs that, with a seven-field schema, per-field role-indexed acceptance, and lineage. MMP is the closest prior art on the data-structure *mechanics*. What the plan adds is the relocation of agency: MMP keeps memory passive and intelligence in the agents; the plan fuses them — the artifact itself negotiates, spawns self-maintenance tasks from its own wants, and participates as a peer. The plan's headline ('data + intelligence as the unit') is precisely the split MMP does not make. The contribution is the agentic artifact, not the typed shared memory; MMP is the proof that the mechanics are buildable and the foil that sharpens what 'living' adds."

**Edit**: rewrite the contribution sections (conclusion + §9) around this. MMP becomes the load-bearing comparison: closest on mechanics, opposite on the agency question. Do NOT drop the framing — the framing *is* the agency relocation, and MMP confirms by contrast that it is a real, un-taken position.

### A3. TheBotCompany (arXiv:2603.25928) — reviewer overstated; it is an *anti-example*, not a preemption

**Verified**: the reviewer called this "a deployed self-organizing software-dev system." It is neither. The abstract describes "an open-source orchestration framework" with "a three-phase state machine" and "manager agents [that] dynamically hire, assign, and fire worker agents" — a **manager hierarchy**, central control, not decentralized coordination. And it is *experimentally evaluated* on real-world projects, not commercially deployed. Agents are the intelligent units; "data artifacts remain passive objects managed by the agent system."

**Decision**: do NOT cite TheBotCompany as a preemption. It is the orchestration-centric design the plan argues against — cite it (briefly, optionally) alongside the commercial Swarms framework as a *contemporary example of the central-coordinator design*, the foil, not the prior art. Do not let "deployed self-organizing" into the lit review; it is false on both words.

### A4. Semantic Consensus (arXiv:2604.16339) — verify before citing

The reviewer's claim is modest: it "formally names the plan's integrity problem." That is a cite-as-related-work claim, lower stakes. **Edit**: the edit agent verifies the abstract; if it formally treats the multi-agent semantic-consistency / integrity problem, cite it in the integrity discussion as related work. If it doesn't match, drop.

## Bucket B — framing and substance findings

### B1. "Keep the framing" shaded into overclaim in 3 places

**Agree.** The draft-feedback round's "keep the framing" instruction was correct, but the edit that applied it overcorrected in three spots — it would prove a plan claim is loose, then certify it as "surviving" anyway. That is the failure mode the methodology principle warns about from the *other* direction (holding the line too hard).

**Edit**: find the three places (the Cycle 1 review names them). For each, the honest move is not "the claim survives" but "the claim, stated precisely, is X" — narrow the *statement*, keep the *direction*. "Keep the framing" means keep the research direction and the headline; it does not mean certify every loose sub-claim.

### B2. "Non-deterministic" is the wrong word for the data-structure pillar

**Partial — flag to the plan owner.** The plan owner's own phrasing of the core contribution used "non-deterministic." The Cycle 1 reviewer is technically right: "non-deterministic" means "outcome not determined by inputs / involves randomness," which is not what is meant. What is meant: *the artifact's state is not a single settled value — it carries in-flight, not-yet-resolved proposals as first-class state.*

**Edit**: the lit review should describe the pillar rather than lean on the word "non-deterministic." Proposed phrasing: "the structure represents unsettled state as first-class — proposals in flight, not just committed content." Keep "non-deterministic" only if paired with that gloss. **Surface to the plan owner**: the word in the plan's own contribution statement may want the same treatment.

### B3. Time-relativity rebuttal hand-waves the economics

**Agree.** The rebuttal to "Drop the Hierarchy"'s strong-model-privilege finding currently asserts the self-organization floor descends as the frontier rises, without engaging the economics. The honest version engages it: the question is not only whether the floor descends but whether it descends *faster than the cost of the tier you want to staff routine tasks with rises in capability*. The rebuttal should say: the plan's cost-stratification bet is that the capability-per-dollar curve keeps moving such that "competent enough to negotiate" becomes affordable at the routine tier — and that the privileged-participant safety net is what makes the bet survivable if the curve moves slower than hoped. State the bet as a bet, with the safety net as the hedge; don't assert the floor descends as if it were settled.

## Bucket C — accessibility (10 items) and prose (6 items)

Apply per the Cycle 1 review's specific text. The accessibility block is Block-3 jargon (actor model, blackboard, CRDT, tuple space, operational transformation, stigmergy) — gloss each for the non-developer audience.

## Edits checklist

1. Cite MAIF as the published precedent for the artifact-centric *framing*; differentiate (MAIF fuses verification into the data layer; the plan fuses agency). Drop any "no one has proposed artifact-centric AI" implication.
2. Rewrite the contribution sections (conclusion + §9) around MMP as the load-bearing comparison: closest prior art on data-structure mechanics (typed schema, per-field semantic acceptance, lineage, cross-session persistence), opposite on the agency question (MMP passive memory + active agents; the plan fuses them). Use the replacement contribution statement from A2.
3. Add MMP, MAIF to References. Note MMP's "three reference deployments" status honestly — running, but reference implementations, not verified commercial adoption.
4. Cite TheBotCompany (optional, brief) as a contemporary central-coordinator example alongside commercial Swarms — the foil, NOT a preemption. Do not use "deployed self-organizing."
5. Verify Semantic Consensus (arXiv:2604.16339); cite as related work on the integrity problem if it matches; drop if not.
6. Fix the 3 "keep the framing → overclaim" spots: narrow the *statement*, keep the *direction*.
7. Replace bare "non-deterministic" with the "unsettled state as first-class" description; flag the same to the plan owner for the plan's own contribution statement.
8. Rewrite the time-relativity rebuttal to engage the economics — state cost-stratification as a bet with the privileged-participant safety net as the explicit hedge.
9. Apply the 10 accessibility glosses and 6 prose nits.

## Plan-owner items

- **The "no one has built this" claim must narrow.** MMP built the passive-shared-memory version and runs it. The plan's contribution is the agentic-artifact inverse. `plan-984dfeb.md`'s framing ("data + intelligence as the unit") is compatible — it is precisely the split MMP doesn't make — but the plan should cite MMP and state the differentiation rather than imply the data structure is unprecedented.
- **"Non-deterministic"** in the plan's own core-claim phrasing: consider replacing with "carries unsettled/in-flight state as first-class." The plan owner used "non-deterministic"; it is imprecise but it is the plan owner's word, so this is a suggestion, not an edit.

## Convergence note

Cycle 1, as expected, found substantive work. The citation-graph walk's recent-LLM-agent axis was the weak spot of the first draft — MMP and MAIF are both from the last six months, the exact failure mode the methodology's step 5 warns about. The verification step then corrected the reviewer's overstatement on two of four finds (MAIF preempts vocabulary not substance; TheBotCompany is an anti-example, not a preemption). The plan's framing survives — narrowed against MMP, which is real and close but is the passive-memory inverse of the plan's agentic-artifact bet. Cycle 2 should expect the contribution rewrite around MMP to be the main thing to pressure-test.
