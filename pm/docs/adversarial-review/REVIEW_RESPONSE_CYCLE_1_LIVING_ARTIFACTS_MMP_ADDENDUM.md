# Addendum — the substantive MMP comparison

Date: 2026-05-15
Supplements: `REVIEW_RESPONSE_CYCLE_1_LIVING_ARTIFACTS.md`, finding A2.

The plan owner asked for a more substantive MMP comparison than "MMP passive, plan active": *what is the plan trying to do re: self-organization, task scheduling, etc. that MMP did or did not target? Building on MMP is fine; "we wrote it ourselves" as the only difference is also fine — but it doesn't sound like that's the case. Be precise about how the "living document" semantics don't match.*

It is not "we wrote it ourselves." MMP and the living-artifacts plan operate at **different layers** and their core *units* are **different kinds of object**. The honest framing is: the plan could *build on* MMP-like primitives for one layer, and the plan's actual subject is a layer MMP does not touch at all.

## What MMP targets (verified from the abstract)

MMP's stated problem is **cross-session agent-to-agent cognitive collaboration** — "agents share, evaluate, and combine each other's cognitive state in real time across sessions." Its three sub-problems:

- **P1** — field-by-field acceptance: an agent decides field by field what to accept from a peer's message, not whole-message accept/reject.
- **P2** — lineage: every claim traceable to source, so a returning claim is recognised as an echo of the receiver's own prior thinking.
- **P3** — storage-relevant memory: memory that survives session restarts, relevant by *how it was stored* rather than *how it is retrieved*.

Its four primitives — CAT7 (seven-field schema for a Cognitive Memory Block), SVAF (per-field role-indexed acceptance), inter-agent lineage, remix (receiver stores its own role-evaluated understanding) — all serve those three problems. **MMP is a protocol for how agents share knowledge.** Its unit, the Cognitive Memory Block, is a *knowledge/message unit passed between agents*.

## What MMP does NOT target

Going through the plan's actual subject matter axis by axis:

### Self-organization of work

- **MMP**: none. MMP is a mesh of agent peers sharing memory. The only "organization" in MMP is the topology of who-shares-with-whom. MMP does not decide what work happens, in what order, or by whom — it is silent on work. "No central arbiter" is trivially true of MMP because *there is no arbitration happening* — nothing is being scheduled or adjudicated.
- **The plan**: self-organization *of work* is the whole subject. Tasks negotiate which proposals run in parallel, preempt one another, or merge. Selection and ordering *emerge from negotiation*. The plan's "no central arbiter" is a substantive claim about coordinating work without a central scheduler — a claim MMP never makes because MMP never coordinates work.

### Task scheduling and lifecycle

- **MMP**: no task concept at all. No queue, no lifecycle, no scheduling. MMP agents do whatever they do; MMP is the cognition-sharing layer beneath them.
- **The plan**: the **task is the atom**. Tasks have a lifecycle (entry → specialization → in-flight → landed/folded/dropped) where each phase is a property of the *live task*, not a queue position. Scheduling is emergent — there is no scheduler; a task's phase is a description of its trajectory through negotiation. This is the plan's core machinery and MMP has no analog of it.

### The unit of the data structure — the "living document" mismatch

This is the precise semantic mismatch the plan owner asked for:

- **MMP's unit (Cognitive Memory Block)** is *what an agent tells other agents* — a knowledge block, produced by one agent, selectively absorbed by others. It is a **message-and-memory unit**. It flows *between* agents.
- **The plan's unit (artifact)** is *what agents work on, and which also works on itself* — a document (a plan file, a PR spec, eventually pm itself) that carries a task queue, a negotiation history, a self-maintenance schedule, and "wants." It is a **work-substrate-with-agency**. It is the thing the work happens *to*, not a thing that flows between workers.

A CMB is a unit of shared cognition. An artifact is a unit of worked-on, self-maintaining structure. A plan file is not "something an agent told another agent" — it is the durable object the whole project is organised around, which the plan makes capable of spawning its own maintenance work. These are different kinds of object; "living document" in the plan's sense (a document with agency over its own coherence) is not what a CMB is.

### Agency and self-maintenance

- **MMP**: the memory is passive. CMBs do not generate tasks, do not have wants, do not negotiate. The intelligence is entirely in the agents; agents decide (via SVAF) what to accept.
- **The plan**: the artifact spawns its own self-maintenance tasks from its own "wants" — coherence checks, stale-content sweeps, integrity-pressure notifications. The artifact is a participant, not a medium.

### Integrity as a shared constraint vs. per-receiver acceptance

- **MMP's SVAF** is *per-receiver* admission control: each agent evaluates each field against *its own* role-indexed anchors. It is a receiver-side filter. There is no notion of a shared object whose integrity all participants are accountable to.
- **The plan's "integrity"** is a property *of the artifact* that every task negotiating over it is accountable to — not a per-receiver filter but a shared constraint that shapes which negotiated outcomes are admissible. A proposal that degrades the artifact's integrity is pushed back on by other tasks and by the artifact's own maintenance tasks, because no integrity-preserving negotiated shape can absorb it. That is a fundamentally different mechanism from SVAF's per-receiver field acceptance.

## The honest framing: build on MMP's layer, the plan's subject is the layer above

MMP solves a real problem the plan also has. The plan's open questions include: *what is the artifact's persistent representation? how does the live state of in-flight tasks persist across pm restarts? what does a task see when prompted to respond to another task's proposal?* MMP's CAT7 typed schema, per-field semantic evaluation, and lineage are a *credible substrate for that persistence-and-sharing layer*. The plan could adopt MMP-like primitives there rather than reinventing them — and the lit review should say so plainly. That is "building on," which is fine and honest.

But the plan's **subject** — task negotiation, emergent work scheduling, the artifact's self-maintenance, integrity as a shared constraint, agency relocated into the artifact — is a layer **above** MMP, one MMP does not address. MMP is a memory protocol; the plan is a work-coordination-and-self-maintenance substrate. The relationship is *layered*, not *competing* and not *identical*.

## Replacement for finding A2's contribution statement

Replace the A2 contribution statement with this more substantive version:

> "The Mesh Memory Protocol (arXiv:2604.19540) solves cross-session agent-to-agent knowledge sharing: a typed memory block (CAT7), per-field role-indexed acceptance (SVAF), and lineage. The living-artifacts plan shares one layer with MMP and could build on it: the artifact's open questions about persistent representation and cross-restart in-flight state are the problem MMP's primitives address, and the plan should adopt MMP-like typed-schema-plus-lineage primitives there rather than reinvent them. But MMP's *subject* and the plan's *subject* differ. MMP coordinates *knowledge* between agents; it has no task concept, no scheduling, no self-organization of work — its 'mesh' is a sharing topology, not a work-coordination mechanism. The plan's subject is exactly what MMP omits: tasks as the atom, a task lifecycle whose phases are trajectories rather than queue positions, work scheduling that emerges from peer negotiation rather than from a scheduler, artifacts that spawn their own self-maintenance from their own 'wants,' and integrity as a constraint the whole negotiation is accountable to rather than a per-receiver acceptance filter. And the units differ in kind: MMP's Cognitive Memory Block is what one agent tells another; the plan's artifact is the durable object the project is organised around, made capable of maintaining itself. The plan builds the work-coordination-and-agency layer; MMP, or a protocol like it, is a candidate memory layer beneath it. The contribution is the upper layer — and 'living document,' in the plan's sense of a document with agency over its own coherence, is not what a CMB is."

## Edit instruction

Replace finding A2's contribution statement (in `REVIEW_RESPONSE_CYCLE_1_LIVING_ARTIFACTS.md`) with the version above when applying the edit pass. The lit review's MMP treatment in §9 / the conclusion should be built around this layered framing — MMP as a candidate substrate beneath, the plan's subject as the layer above — and should explicitly walk the self-organization / task-scheduling / unit-of-the-data-structure axes, because those are where the mismatch is precise and load-bearing. Do not flatten this back to "passive vs. active."
