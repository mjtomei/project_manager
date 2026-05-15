# Literature Review: Living Artifacts — Data + Intelligence as the Unit

*A survey of the prior work surrounding `plan-984dfeb.md` ("Living artifacts: data + intelligence as the unit"), written for a reader evaluating whether the plan's central bet is supported by — or contradicted by — existing research.*

---

## Executive summary — is the plan's bet supported?

**The short answer: yes, though the plan should claim less as brand-new than it might want to.** This review checked the plan's central idea — building software files that are not passive documents but active participants that argue out their own changes — against the published research. The idea is not preempted. But recent work has built pieces of it, so the claim of what is *new* has to be stated carefully.

What the plan builds, in plain terms: instead of a file being a finished document that some separate program edits, the file keeps track of its own half-decided, still-being-argued-over changes, knows how it connects to other files, and uses an AI to settle disagreements between competing changes.

The three closest published papers, and the one-line verdict on each:

- **AgentNet (2025)** built a system where AI agents coordinate with no central manager. Verdict: it proves the no-manager idea works, but it coordinates *agents*, not self-maintaining *files*. Does not preempt the plan.
- **ScienceClaw + Infinite (2026)** built a layer that automatically cleans up when automated research tools produce contradictory or duplicated results. Verdict: closest published thing to the plan's self-maintenance, but its files are passive records; the plan's files have their own goals. Does not preempt the plan.
- **The Mesh Memory Protocol** is the nearest shared-memory system. Verdict: it solves a different problem (shared memory across agents), not a competing one.

**Bottom line:** the plan inherits a great deal and is honest that it does. What is new is putting *agency* — goals, negotiation, self-repair — into the file itself, as a general substrate (the common underlying machinery everything is built on) inside a working tool. That is an old vision that only became buildable because AI now makes "settle the disagreement with judgment" a cheap, repeatable step. The body below grounds the contribution in four concrete cases; the full evidence is in two appendices.

---

## Introduction

### What the plan proposes

The plan called `plan-984dfeb.md` makes one central move. Today, in almost every computing system, **data is passive** (files, records, rows in a database) and **intelligence is separate** (the scripts, models, or people that read the data and change it). A thin layer of "orchestration code" sits between the two: it watches the data, decides what to do, and rewrites the data. The plan proposes to collapse that split. Every *artifact* in a software-project-management tool — a plan document, a pull-request specification, the tool's own internal state, and eventually source code itself — becomes a **living unit** that carries both its own content and its own intelligence.

A few terms, glossed up front, because the rest of this review leans on them:

- A **pull request** (PR) is the standard unit of proposed change in modern software work: a bundle of edits with a description, reviewed before it is accepted ("merged"). "pm" is the project-management tool this plan extends; it tracks plans and PRs as text files.
- An **artifact**, in this plan, is any such tracked thing — a plan file, a PR spec, the tool's state.
- An **LLM** (large language model) is the kind of AI system, such as Claude, that reads and writes text. The plan assumes every artifact's "intelligence" is supplied by an LLM.
- A **negotiation**, here, is two or more in-progress changes (the plan calls them *tasks*) exchanging proposals about how to coexist — run in parallel, merge into one, or back off — instead of being scheduled by a central manager.

With those in hand, the plan's specific claims are:

1. **The unit fuses data and intelligence.** Each artifact has content *and* "wants," a capacity to negotiate, and self-maintenance behavior.
2. **Adjudication is relocated, not eliminated.** Tasks negotiate peer-to-peer; conflicts resolve against a shared constraint the plan calls *artifact integrity* — a property each task is *accountable to*. The plan does not claim adjudication disappears. It claims the system can maintain itself, in whole or part, without the adjudicators it depends on today (human review, pm's central state machine), by carrying adjudication as the artifact substrate's (the common underlying machinery) own integrity-maintenance tasks.
3. **The human becomes a boundary, not a bottleneck.** Most work never reaches a person; humans (and "watchers" — automated supervisory processes) are *privileged participants* whose voice carries more weight, but they are still participants, not observers above the system.
4. **General intelligence removes a historical ceiling.** The plan claims earlier coordination systems — actor models, contract-net, blackboards — "gestured at this but were boxed in by determinism and programmability constraints" and "assumed a central scheduler or arbiter." It claims that putting a *generally intelligent* LLM in every unit lifts that ceiling.
5. **Where it leads.** As a stretch goal, the plan claims living units enable "a qualitatively different mode" of evolutionary computation — a community of living units rather than a population of passive strings.

This review surveys the literature each of those claims sits in. The body proper grounds the plan in the four concrete instances it commits to building in pm, gives a brief tour of the prior art, and concludes — point by point — on where the plan inherits, diverges, and is new. The dense prior-work survey lives in two appendices: Appendix A walks Claude Code feature-by-feature, and Appendix B is the full §§1–7 survey of coordination, concurrency, agents, and evolutionary computation. A companion review, `literature-review-user-model.md`, covers persona and role-prompting in depth.

### What surrounds the plan

The short version, previewed here so the reader can calibrate: almost every *primitive* the plan needs already exists in a mature form. Decentralized coordination without a scheduler is fifty years old (actor model, 1973). Negotiation-by-bidding is forty-five years old (contract-net, 1980). Indirect coordination through a shared workspace is the blackboard model and Linda tuple spaces. Merging concurrent edits without a central referee is a solved problem (operational transformation, 1989; conflict-free replicated data types, 2011). The "document that is also a program" is literate programming (1984) and computational notebooks. And the last twelve months have produced LLM-agent systems close to the plan's architecture: decentralized multi-agent coordination over a shared state (CodeCRDT, 2025), AI agents as peers in a conflict-free replicated document (Yjs-based agent work, 2026), and a large empirical study that directly tests "self-organizing agents vs. designed hierarchies" (the "Drop the Hierarchy" paper, 2026).

The plan's framing — "we study the prior work for inspiration and vocabulary, not as a blueprint" — turns out to be exactly the right posture. The plan's central direction survives this survey, narrowed but intact. The plan builds something new on top of the project's files. Instead of a file being a finished document that something else edits, the file keeps track of its own half-decided, still-being-argued-over changes, knows how it connects to other files (it is *relational* — the artifact records how it connects to other artifacts, not just its own contents), and uses an AI to settle disagreements between competing changes — work that until recently no software could do, because the "settle the disagreement" step needs judgment, and only a person could supply judgment. ("First-class" is a programming term used below: it means the half-finished, still-being-argued-over version of the document is stored and handled as seriously as the finished version, not bolted on as an afterthought. The plan also speaks of proposals in *superposition* — many possible versions of the document held at once, none yet the final one.) It is a vision people have gestured at before; what is new is that large language models make it buildable.

Two 2026 works sit closest and must be named at the outset, because the survey is in part a response to them. The **Mesh Memory Protocol** (MMP, arXiv:2604.19540) specifies and runs a typed, semantically-merged, cross-session shared memory for LLM agents; it is the closest prior art on the *mechanics* the plan's substrate needs, and worth a precise comparison. **MAIF** (arXiv:2511.15097) names an "artifact-centric AI agent paradigm where behavior is driven by persistent data artifacts," so the plan cannot claim that phrasing as unprecedented. Neither preempts the plan's actual subject: MMP coordinates *knowledge* between agents and has no concept of work, tasks, or scheduling; MAIF fuses *verification* into the data layer, not agency. The plan's subject is the layer above both: work that self-organizes through negotiation, an artifact made capable of maintaining itself.

---

## The plan's instances, grounded in pm

This section is the most concrete in the review: for each of the four things the plan actually commits to building, it shows what pm does today, what breaks, and what changes. It grounds the plan against the tool the plan actually changes — pm itself. The prior-art survey (in brief below, in full in Appendix B) supplies a vocabulary — blackboard, actor, tuple space, market coordination; this section spends that vocabulary on the four concrete things the plan commits to building, in the order the plan builds them.

A reminder of two pm terms used throughout, glossed for a reader who has not used the tool: a **plan** is a markdown file (under `plans/`) that lays out a body of intended work as a list of pull requests; **`project.yaml`** is pm's single bookkeeping file, tracking every plan and pull request and its current status. A **watcher** is an automated supervisory process pm runs in the background — it polls for a condition (a stuck pull request, say) and acts when it sees one.

### Instance 1 — plan files become living artifacts

**pm today.** A plan is static markdown (`plans/*.md`) plus a one-line entry in `project.yaml`. Keeping that plan coherent — auditing that its pull requests still depend on each other sensibly, checking that the narrative still flows, noticing when a pull request has quietly drifted from the plan's stated motivation — is manual work. A human does it, or runs a dedicated "plan-review" session to do it. The adversarial-review effort that produced *this very literature review* is an instance of the pain: across several cycles, a human kept noticing the plan and its documents drifting apart and kept prompting coherence fixes by hand. Nothing in pm spots that drift on its own.

**Living-artifact version.** The plan stops being inert text. It carries its own task queue and its own self-maintenance schedule. The coherence-check is no longer a thing a human remembers to run; it becomes a self-maintenance task the plan artifact spawns from its own "wants" (the plan, framed as wanting its pull requests to stay coherent with its motivation, generates the check as work).

**What it enables.** The plan notices its own staleness. When a pull request's description drifts from the plan's motivation, that surfaces as a negotiation between the drifting pull request and the plan's maintenance task — immediately — rather than waiting for the next time a human sits down for a plan-review session. The hand-run coherence loop becomes a standing property of the artifact. The adversarial-review cycle above is the concrete before-and-after: what a human did by repeated prompting becomes something the plan does for itself.

### Instance 2 — PRs become living artifacts

**pm today.** A pull request's specification is markdown. The flow that carries it from implementation through review, testing, and merge is pm orchestration code — a state machine that watches each pull request's status and advances it one step at a time. When a pull request gets stuck (its testing phase keeps failing), an external bug-fix watcher detects the impasse from outside, by pattern-matching repeated failure. The pull request itself is mute; something else has to notice it is in trouble.

**Living-artifact version.** The pull request's specification *is* the document; the implementation, review, testing and merge phases become tasks in the pull request's own queue; what pm did as orchestration becomes negotiation inside the pull request artifact. This draws on the actor-as-negotiating-peer and contract-net primitives (Appendix B §1): the phases become peer tasks that negotiate the content of the change, not just its scheduling, rather than steps a state machine advances.

**What it enables.** A stuck pull request surfaces its own impasse. Instead of an external watcher inferring "this is stuck" from the outside, the pull request's own self-maintenance raises the impasse as a want — the artifact says it is stuck. The watcher's stuck-detection logic stops being external scaffolding and becomes the artifact's own concern.

### Instance 3 — pm's orchestration becomes the artifact protocol

**pm today.** pm is a state machine, and `project.yaml` holds the workflow state that machine runs on. That central state is a recurring source of friction: it is a single file many processes contend over, so concurrent work collides on it — merge conflicts on `project.yaml`, a merge already in progress when another wants to start, stale-state notifications when one process's view falls behind.

**Living-artifact version.** pm becomes a renderer and a host. Every flow it runs today — starting a pull request, reviewing, testing, merging, the watchers, synchronization — becomes a *task type* over the artifact substrate. `project.yaml` no longer holds workflow state at all. Structurally, the artifact substrate pm then hosts is a tuple space (Appendix B §1) — coordination through a shared pool rather than through a central orchestrator.

**What it enables.** It removes the central state machine. This is where the plan's coordination claim gets its most concrete grounding, and it should be stated precisely. pm's state machine is, today, the adjudicator the system depends on: every flow routes through it, and it decides what advances. Instance 3 does not eliminate adjudication; it removes the system's dependence on *that* adjudicator by relocating adjudication into the artifact substrate's own integrity-maintenance tasks. The claim is not abstract: it names a specific component of pm and commits to internalizing what that component does into the living substrate, so the substrate carries its own integrity maintenance rather than depending on an external state machine to enforce it.

### Instance 4 — code as living artifacts (stretch study)

**pm today.** Nothing. pm does not touch program optimization at all; this instance is entirely new ground.

**Living-artifact version.** Functions and modules become living artifacts that negotiate optimizations peer-to-peer, applying the market-based, decentralized-coordination lineage (Appendix B §5). The plan's worked scenario: code-artifact A notices, through its own profiling-driven self-maintenance, that it spends most of its time on a task X coming from artifact Y, and opens a negotiation directly with Y — proposing, for instance, that Y send X less often or pre-aggregated — with no central optimizer brokering the exchange.

**What it enables.** Autonomous program optimization with no central profiler-plus-optimizer. The system's pieces tune themselves in parallel; the human sits at the boundary, surfacing only where the artifacts could not resolve something, not on the critical path of every optimization.

### Where these instances lead

Instances 1–4 are what the plan commits to building. The plan also names four follow-on directions the same substrate would unlock once it exists: **new shapes of evolutionary algorithm** (a population of living candidates that negotiate their own selection, rather than passive genomes scored by an external fitness function — see Appendix B §6); **self-organizing knowledge bases** (notes and references that maintain their own links and negotiate consolidation); **self-tuning infrastructure** (configuration and services that observe their own efficacy and converge without a human operator); and **living research workflows** (hypotheses and experiments that surface to the researcher only when consensus among them breaks down). **"The Last Human-Written Paper: Agent-Native Research Artifacts" (arXiv:2604.24658, 2026)** proposes machine-executable research packages with a "Live Research Manager" — adjacent to the plan's "living research workflows" direction, though it externalizes a research package rather than giving the artifact agency. These are not on the plan's critical path; they are substrate-enabled follow-ons, each a domain where the same data structure removes a bottleneck currently handled by external orchestration. The plan's job is to build the substrate well enough that any of them becomes a low-friction next step.

---

## Prior art in brief

Eight clusters of prior work surround the plan. Each is summarized here in a few sentences; the full treatment, system by system, is in Appendix B.

**Classical coordination without a scheduler.** The actor model (1973), contract-net (1980), blackboard systems (1980), and Linda tuple spaces (1985) all coordinate work without a central manager. The plan's claim that they "assumed a central scheduler" is true only of classic blackboards; the load-bearing critique is that all four made the per-unit intelligence small and fixed. Full treatment in Appendix B §1.

**Concurrent shared state — CRDTs and OT.** Operational transformation (1989) and conflict-free replicated data types (2011) solved decades ago the problem of many edits to one document with no central referee. The plan inherits this; its open question — how to persist *unsettled* in-flight task state — is narrowed but not closed by it. Full treatment in Appendix B §2.

**The living-document vision.** Engelbart's NLS (1962/68), Bret Victor's responsive media, and literate programming / computational notebooks (1984 onward) are all precedents for a document that is also a live, working thing. The plan inherits the aspiration and inverts the audience (machine-primary, human-auditable). Full treatment in Appendix B §3.

**LLM agents, memory, and the "LLM-OS" framing.** Society of Mind (1986), MemGPT (2023), Karpathy's LLM-OS framing, and MAIF (2025) supply the agent-and-memory vocabulary the plan reaches for. MAIF in particular already names an "artifact-centric AI agent paradigm," so the plan cannot claim that phrase. Full treatment in Appendix B §4.

**Self-organizing and emergent coordination.** Stigmergy, market-based coordination, and a 2025–2026 cluster (Semantic Consensus, SwarmSys, AgentNet, ScienceClaw, "Drop the Hierarchy", Agora-Opt) are the closest academic neighbors — they corroborate decentralized coordination but none builds a general self-maintaining artifact substrate. Full treatment in Appendix B §5.

**Evolutionary computation.** Novelty search loosened the external-fitness pillar; Promptbreeder, FunSearch, AlphaEvolve, ADAS and A-Evolve loosened the passive-genome pillar. The plan's evolutionary claim narrows to one untested sliver — *negotiated internal selection*. Full treatment in Appendix B §6.

**Anthropomorphization as a prompt technique.** Persona prompting demonstrably changes LLM output, but the specific framing "anthropomorphize a non-agent artifact as having wants" is untested; the plan should run a cheap controlled comparison. Full treatment in Appendix B §7.

**Claude Code as the grounding tool.** Claude Code assumes a static-config + reactive-session split with no first-class between-sessions artifact. The frontier (InfiAgent, "Everything is Context") builds file-as-state but passive or human-curated. Full treatment in Appendix A and the Appendix B §8 pointer.

---

## Conclusion: an old vision, newly buildable

The plan's contribution is best stated in one sentence, and the whole survey is the case for it: **the plan builds a work-coordination-and-agency layer over artifacts — a data structure that holds unsettled, in-flight state as first-class (the half-decided, still-being-argued-over version of an artifact, stored as seriously as the finished version), is relational (it records how it connects to other artifacts, not just its own contents), and is intelligence-resolved (an AI settles conflicts) — and the closest prior art, the Mesh Memory Protocol, addresses a different problem, not a competing one.** That is the claim. It is, deliberately, "something people have gestured at before, newly enabled by LLMs." This conclusion makes that case in four steps.

### (a) The vision is old — and the plan should say so plainly

Nothing in the aspiration is unprecedented. Engelbart's NLS imagined the document as a live, shared surface between human and machine; blackboard systems imagined a shared workspace multiple intelligences coordinate through; the actor model imagined autonomous units coordinating without a central clock; Linda tuple spaces imagined coordination through a shared content-addressed pool. Each holds a piece of "living artifacts," and the plan's vision is assembled from parts that have been in the literature for decades. The plan's posture — "inspiration, not blueprint" — is right, and it should claim the lineage proudly. The one update the survey forces: "blackboard" is not a forty-year-old word but a live 2026 research term, being actively rebuilt for LLM agents (Appendix B §1).

### (b) Why the prior visions stalled — the determinism constraint

These visions did not become the general substrate the plan describes for one shared reason: in every one of them, the per-unit "intelligence" had to be deterministic and programmed in advance. An actor's behavior is a fixed program; a blackboard knowledge source is a hand-written specialist; a CRDT merges by a fixed mathematical law. When two edits conflict, or an artifact's state stops cohering, something has to decide what to do — and in all the prior work that something was a deterministic rule or a central arbiter running one. You could not put open-ended judgment inside the structure, because open-ended judgment did not exist as a component you could instantiate cheaply and ubiquitously. CodeCRDT measures the cost of that constraint: a CRDT gives guaranteed syntactic convergence and still leaves 5–10% of conflicts semantically unresolved — the residue that needs judgment, not a merge rule.

### (c) What LLMs change — intelligent conflict resolution as a primitive

What LLMs change is that intelligent conflict resolution becomes cheap enough to instantiate *inside a data structure* — the way a sort function or a hash table is a component. This is no longer unprecedented: intelligent conflict resolution is an active 2025–2026 research direction, and multiple systems now put LLM judgment in a reconciliation step on narrower problems. Agora-Opt does outcome-grounded decentralized reconciliation for optimization modeling (Appendix B §5); the revived LLM-blackboard systems let agents self-select what to contribute to a shared board (Appendix B §1); CodeCRDT's own measured 5–10% semantic residue motivates exactly this layer. What the plan adds within that direction is the artifact-centric, agency-bearing version: it makes intelligence the resolution layer of a *general, self-maintaining artifact substrate* — not a narrow problem class, and with no solver oracle to ground the judgment, where Agora-Opt has one.

### (d) The plan's contribution — building that data structure on a real substrate

The contribution is not the vision and not the enabler. It is **specifying and building the data structure the enabler now permits, and proving it on a real substrate.** Concretely, that data structure is:

- **Unsettled state as first-class.** Unlike a markdown file or a database row, the artifact's state is not a single committed value. The structure represents unsettled state as first-class: proposals in flight, not just committed content — in-flight, not-yet-resolved tasks converging through negotiation. (The plan's own contribution statement uses the word "non-deterministic" for this property; it is imprecise, and the plan owner may want to replace it with this description of unsettled-state-as-first-class.)
- **Relational.** The artifact carries its relations, not only its content: negotiation history, cross-artifact references, the want-dependencies between an artifact and the tasks acting on it and the artifacts around it. Artifacts negotiate with each other; the structure makes those relations legible.
- **Intelligence-resolved.** Conflicts are resolved by LLM reasoning over the artifact-integrity constraint, rather than by a deterministic merge rule or an adjudicator the system depends on from outside. Adjudication is not eliminated — it is relocated into the substrate's own integrity-maintenance tasks, so the system carries progressively more of its own integrity maintenance without the external adjudicators (human review, pm's central state machine) it relies on today. This is the part that was impossible before, and the part the prior visions could only gesture at.

The plan proves the data structure by building it in sequence on a real substrate — the four instances above. It carries the structure into a working project-management tool, then into code itself. This is not a research demo.

### The closest prior art — the Mesh Memory Protocol — a precise comparison

The single closest work to the plan is the **Mesh Memory Protocol** (MMP, arXiv:2604.19540, 2026), and the relationship is worth stating with care, because the two systems are close on data-structure mechanics yet address different problems — neither competing nor identical.

MMP solves cross-session agent-to-agent knowledge sharing. Its four primitives are a fixed seven-field typed schema (CAT7) for a "Cognitive Memory Block" — the knowledge unit one agent passes to another; an accept-field-by-field rule, where a receiver decides field by field what to take from a peer; inter-agent lineage, so every claim is traceable to its source; and remix, where a receiver stores its own role-evaluated understanding of what it accepted. MMP is "specified, shipped, and running in production across three reference deployments" — which the references note honestly: running, but in the authors' own reference implementations, not verified commercial third-party adoption.

MMP's subject and the plan's subject differ in kind. MMP coordinates knowledge between agents — its "mesh" is a sharing topology, with no task concept, no scheduling, and no self-organization of work — while the plan coordinates work and relocates agency into the artifact itself, with tasks as the atom and a self-maintaining artifact MMP has no analog of. The plan's subject is exactly what MMP omits: tasks as the atom, a task lifecycle whose phases are trajectories rather than queue positions, work scheduling that emerges from peer negotiation rather than from a scheduler, artifacts that spawn their own self-maintenance from their own "wants," and integrity as a constraint the whole negotiation is accountable to rather than a per-receiver acceptance filter. The plan is therefore not the first typed, semantically-merged, cross-session shared memory — MMP runs that — but the contribution is the work-coordination-and-agency layer, and "living document," in the plan's sense of a document with agency over its own coherence, is not what MMP's memory block is.

### The other close prior art points the same way

Every close prior-art work surveyed corroborates the plan's direction on a narrower slice; none builds the general self-maintaining artifact substrate — that layer is the plan's job. CodeCRDT, SwarmSys, AgentNet, ScienceClaw, "Drop the Hierarchy", MAIF, Agora-Opt, and the three uncited 2026 papers (Ψ-Arch, First-Class Intermediate Artifacts, Loosely-Structured Software) are treated in full in Appendix B §§4–6.

### Read on the framing

The plan's research direction survives this survey; three of its sub-claims need narrowing in the plan's own text. The plan's four boldest moves — that prior coordination systems were boxed in by determinism, that the system can maintain itself without the adjudicators it depends on today, that living units open a different mode of evolutionary computation, that the "wants" scaffold is operational and not decorative — hold as directions, with these calibrations:

- The determinism diagnosis is the strong half of the prior-systems claim; the "central scheduler" half is false for three of the four systems and the plan should narrow that sentence (Appendix B §1).
- "No central arbiter" should not be stated as an absolute. As the relocation argument in Appendix B §5 sets out, adjudication is not eliminated; it is relocated, and the honest claim is "in whole or part." This sharpens the plan's "human as boundary, not bottleneck" framing.
- The evolutionary-computation direction does not "hold" as a headline; Appendix B §6 shows it is mostly inherited. It narrows to a single untested sliver — *negotiated internal selection* — which the plan should carry openly as a narrow long-term direction.
- The "wants" scaffold is grounded in the persona-prompting literature, with a cheap confirmatory experiment named (Appendix B §7).

### Coverage gaps in this review

- **The specific framing "anthropomorphize a non-agent artifact as having wants"** has no direct empirical study that this review could locate; Appendix B §7's verdict rests on analogy to person-persona prompting.
- **Negotiated, internal selection for evolutionary computation** (Appendix B §6) is unclaimed *and* untested — this review can say no one has done it, but not whether it works.
- **The semantic-conflict rate for prose-and-task artifacts** is unmeasured. CodeCRDT's 5–10% figure is one measurement of code-merge conflicts in a single 600-trial preprint; the corresponding rate for the plan, PR, and task artifacts the plan actually operates on is not established.
- **Whether LLM-to-LLM proposal negotiation reliably terminates** (Appendix B §5) is an open empirical risk; multi-agent-debate work documents non-termination and false consensus, and whether the plan's timeout-into-dropped rule is sufficient is untested.
- **Some classic sources** (Agha's 1986 actor semantics, Nii's 1986 blackboard survey, the Dias 2006 market-coordination survey) were characterized from abstracts and secondary summaries rather than full-text reads.
- **"Drop the Hierarchy and Roles" (arXiv:2603.28990)** is very recent (2026) and a preprint not yet peer-reviewed; its 25,000-run result is load-bearing and should be re-checked against any published version.

---

## References

### Peer-reviewed

- Carriero, Nicholas, and David Gelernter. 1992. "Coordination Languages and Their Significance." *Communications of the ACM* 35(2): 97–107.
- Dias, M. Bernardine, Robert Zlot, Nidhi Kalra, and Anthony Stentz. 2006. "Market-Based Multirobot Coordination: A Survey and Analysis." *Proceedings of the IEEE* 94(7): 1257–1270.
- Ellis, Clarence A., and Simon J. Gibbs. 1989. "Concurrency Control in Groupware Systems." *Proceedings of the 1989 ACM SIGMOD International Conference on Management of Data*: 399–407.
- Erman, Lee D., Frederick Hayes-Roth, Victor R. Lesser, and D. Raj Reddy. 1980. "The Hearsay-II Speech-Understanding System: Integrating Knowledge to Resolve Uncertainty." *ACM Computing Surveys* 12(2): 213–253.
- Fernando, Chrisantha, Dylan Banarse, Henryk Michalewski, Simon Osindero, and Tim Rocktäschel. 2024. "Promptbreeder: Self-Referential Self-Improvement via Prompt Evolution." *Proceedings of the 41st International Conference on Machine Learning* (ICML 2024).
- Gelernter, David. 1985. "Generative Communication in Linda." *ACM Transactions on Programming Languages and Systems* 7(1): 80–112.
- Hewitt, Carl, Peter Bishop, and Richard Steiger. 1973. "A Universal Modular ACTOR Formalism for Artificial Intelligence." *Proceedings of the 3rd International Joint Conference on Artificial Intelligence* (IJCAI): 235–245.
- Hu, Shengran, Cong Lu, and Jeff Clune. 2025. "Automated Design of Agentic Systems." *International Conference on Learning Representations* (ICLR 2025). [Preprint arXiv:2408.08435.]
- Knuth, Donald E. 1984. "Literate Programming." *The Computer Journal* 27(2): 97–111.
- Lehman, Joel, and Kenneth O. Stanley. 2011. "Abandoning Objectives: Evolution Through the Search for Novelty Alone." *Evolutionary Computation* 19(2): 189–223.
- Nii, H. Penny. 1986. "The Blackboard Model of Problem Solving and the Evolution of Blackboard Architectures" (Parts One and Two). *AI Magazine* 7(2): 38–53 and 7(3): 82–106.
- Qian, Chen, et al. 2024. "ChatDev: Communicative Agents for Software Development." *Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics* (ACL 2024).
- Romera-Paredes, Bernardino, et al. 2023. "Mathematical Discoveries from Program Search with Large Language Models" (FunSearch). *Nature* 625: 468–475.
- Salewski, Leonard, Stephan Alaniz, Isabel Rio-Torto, Eric Schulz, and Zeynep Akata. 2023. "In-Context Impersonation Reveals Large Language Models' Strengths and Biases." *Advances in Neural Information Processing Systems* 36 (NeurIPS 2023).
- Shapiro, Marc, Nuno Preguiça, Carlos Baquero, and Marek Zawirski. 2011. "Conflict-Free Replicated Data Types." *Stabilization, Safety, and Security of Distributed Systems* (SSS 2011), LNCS 6976: 386–400. Springer.
- Smith, Reid G. 1980. "The Contract Net Protocol: High-Level Communication and Control in a Distributed Problem Solver." *IEEE Transactions on Computers* C-29(12): 1104–1113.

### Books and monographs

- Agha, Gul. 1986. *Actors: A Model of Concurrent Computation in Distributed Systems.* MIT Press.
- Minsky, Marvin. 1986. *The Society of Mind.* Simon & Schuster.

### Reports and technical documents

- Engelbart, Douglas C. 1962. "Augmenting Human Intellect: A Conceptual Framework." SRI Summary Report AFOSR-3223, Stanford Research Institute.
- Engelbart, Douglas C., and the Augmentation Research Center. 1968. Public demonstration of the oN-Line System (NLS), Fall Joint Computer Conference, San Francisco ("The Mother of All Demos").

### Preprints (not yet peer-reviewed at time of writing)

- Dochkina, Victoria. 2026. "Drop the Hierarchy and Roles: How Self-Organizing LLM Agents Outperform Designed Structures." arXiv:2603.28990.
- "CodeCRDT" authors. 2025. "CodeCRDT: Observation-Driven Coordination for Multi-Agent LLM Code Generation." arXiv:2510.18893.
- "Collaborative Document Editing with Multiple Users and AI Agents." 2025. arXiv:2509.11826.
- "MAIF: Enforcing AI Trust and Provenance with an Artifact-Centric Agentic Paradigm." 2025. arXiv:2511.15097. [Proposes an artifact-centric AI agent paradigm; its "production-ready" claim is a throughput benchmark, not a deployed-with-users claim.]
- "Mesh Memory Protocol: Semantic Infrastructure for Multi-Agent LLM Systems." 2026. arXiv:2604.19540. [Specified, shipped, and running in production across three reference deployments — running, but in the authors' own reference implementations, not verified commercial third-party adoption.]
- "Semantic Consensus: Process-Aware Conflict Detection and Resolution for Enterprise Multi-Agent LLM Systems." 2026. arXiv:2604.16339. [Formally names "Semantic Intent Divergence"; proposes a Semantic Consensus Framework with conflict detection and drift monitoring.]
- "TheBotCompany: A Self-Organizing Multi-Agent System for Continuous Software Development." 2026. arXiv:2603.25928. [An open-source orchestration framework with a three-phase state machine and a manager hierarchy; experimentally evaluated, not deployed.]
- Han, Bochen, and Songmao Zhang. 2025. "Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture." arXiv:2507.01701. [First LLM implementation of the classical blackboard architecture; competitive with SOTA multi-agent systems at lower token cost. Revives the blackboard pattern for LLM agents but the board remains passive shared state and a selection step still picks contributors.]
- Salemi, Alireza, Mihir Parmar, Palash Goyal, Yifeng Song, Hwanjun Yoon, Hamed Zamani, Tomas Pfister, and Hamid Palangi. 2025. "LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science." arXiv:2510.01285. [Blackboard-shaped data-discovery system; reports 13–57% relative gains in end-to-end success. Retains a central agent that posts requests — it decentralizes only the capability knowledge a coordinator would need, not the central node.]
- Lin, Jianghao, Zi Ling, Chenyu Zhou, Tianyi Xu, Ruoqing Jiang, Zizhuo Wang, and Dongdong Ge. 2026. "From Soliloquy to Agora: Memory-Enhanced LLM Agents with Decentralized Debate for Optimization Modeling" (Agora-Opt). arXiv:2604.25847. [Decentralized outcome-grounded reconciliation of candidate solutions for optimization modeling; agent-centric, solver-oracle grounded.]
- Yu, Chenglin, Yuchen Wang, Songmiao Wang, Hongxia Yang, and Ming Li. 2026. "InfiAgent: An Infinite-Horizon Framework for General-Purpose Autonomous Agents." arXiv:2601.03204. [Bounds a single long-horizon agent's reasoning context by externalizing persistent state into a file-centric state abstraction; passive externalized memory, not multi-party authoritative state.]
- Xu, Xiwei, Robert Mao, Quan Bai, Xuewu Gu, Yechao Li, and Liming Zhu. 2025. "Everything is Context: Agentic File System Abstraction for Context Engineering." arXiv:2512.05470. [A file-system abstraction for context engineering — persistent, governed, human-curated context infrastructure; passive infrastructure, not an artifact with agency.]
- Yang, Yingxuan, Huacan Chai, Yuanyi Shao, Yuanyi Song, Zhaoyang Qi, Yiwei Rui, and Weinan Zhang. 2025. "AgentNet: Decentralized Evolutionary Coordination for LLM-based Multi-Agent Systems." arXiv:2504.00587. [A built, evaluated framework for decentralized agent-to-agent coordination over an adaptive DAG with no central orchestrator; coordinates agents, not artifacts — no shared in-flight-state data structure, no task lifecycle, no wants.]
- Wang, Yuchen, Roman Marom, Subho Pal, Khang Luu, Yangxinyu Lu, Eli Berkovich, and Markus J. Buehler. 2026. "Autonomous Agents Coordinating Distributed Discovery Through Emergent Artifact Exchange" (ScienceClaw + Infinite). arXiv:2603.14312. [Plannerless multi-agent scientific investigation with an artifact layer of immutable provenance records; an autonomous mutation layer prunes the artifact DAG. Agency sits in the agents — the artifacts are passive provenance nodes, not negotiating peers with their own wants.]
- Zhou, et al. 2026. "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering." arXiv:2604.08224. [A 54-page survey arguing modern LLM agents are built by externalizing capability into memory, skills, protocols and harness rather than by changing weights; the umbrella reference for the B§4/B§8 file-as-state cluster.]
- Lin, et al. 2026. "Position: Agentic Evolution is the Path to Evolving LLMs" (A-Evolve). arXiv:2602.00359. [A position paper proposing A-Evolve — evolution as goal-directed optimization over persistent system state — and an evolution-scaling hypothesis; single-system self-improvement, not a population negotiating its own selection.]
- Grötschla, Florian, Luca A. Müller, Jan Tönshoff, Mikhail Galkin, and Bryan Perozzi. 2025. "AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent LLMs." arXiv:2507.08616. [A benchmark for multi-agent self-organization and coordination drawn from distributed-systems and graph-theory problems, scaling to 100 agents.]
- Liu, Pei, Huang, Si, Qu, et al. 2026. "The Last Human-Written Paper: Agent-Native Research Artifacts." arXiv:2604.24658. [Proposes machine-executable research packages (ARA) with a "Live Research Manager"; externalizes a research package rather than giving the artifact agency.]
- Rodriguez-Cardenas, Daniel, David Nader Palacio, and Denys Poshyvanyk. 2026. "Towards Enabling An Artificial Self-Construction Software Life-cycle via Autopoietic Architectures" (Ψ-Arch). arXiv:2604.13934. [A position paper proposing autopoietic architectures for self-constructing, self-maintaining software; an aspirational single-program direction, not a built system.]
- Rosen, Josh, and Seth Rosen. 2026. "Intermediate Artifacts as First-Class Citizens: A Data Model for Durable Intermediate Artifacts in Agentic Systems." arXiv:2605.12087. [Proposes typed, structured, versioned, dependency-aware durable intermediate artifacts as a systems-level data model; the artifacts carry no agency and are completed work-products.]
- Zhang, Zhou, Qu, and Li. 2026. "Loosely-Structured Software: Engineering Context, Structure, and Evolution Entropy in Runtime-Rewired Multi-Agent Systems." arXiv:2603.15690. [Proposes a three-layer framework including "Evolution Engineering" to govern the lifecycle of self-rewriting artifacts; the artifacts are files the agents rewrite, not negotiating peers.]
- Deshpande, Ameet, Vishvak Murahari, Tanmay Rajpurohit, Ashwin Kalyan, and Karthik Narasimhan. 2023. "Toxicity in ChatGPT: Analyzing Persona-Assigned Language Models." Findings of EMNLP 2023. arXiv:2304.05335.
- Gupta, Shashank, et al. 2023. "Bias Runs Deep: Implicit Reasoning Biases in Persona-Assigned LLMs." arXiv:2311.04892.
- Hong, Sirui, et al. 2023. "MetaGPT: Meta Programming for a Multi-Agent Collaborative Framework." arXiv:2308.00352.
- Novikov, Alexander, et al. 2025. "AlphaEvolve: A Coding Agent for Scientific and Algorithmic Discovery." arXiv:2506.13131.
- Packer, Charles, et al. 2023. "MemGPT: Towards LLMs as Operating Systems." arXiv:2310.08560.
- "SwarmSys: Decentralized Swarm-Inspired Agents for Scalable and Adaptive Reasoning." 2025. arXiv:2510.10047.
- Wu, Qingyun, et al. 2023. "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation Framework." arXiv:2308.08155.

### Industry, blog, and non-peer-reviewed sources

- Anthropic. "How Claude Code Works in Large Codebases: Best Practices and Where to Start." claude.com blog. https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start
- Carvalho, Otávio. "Our AI Orchestration Frameworks Are Reinventing Linda (1985)." https://otavio.cat/posts/ai-orchestration-reinventing-linda/
- Electric. 2026. "AI Agents as CRDT Peers — Building Collaborative AI with Yjs." https://electric.ax/blog/2026/04/08/ai-agents-as-crdt-peers-with-yjs
- Karpathy, Andrej. 2023–2024. "LLM OS" framing (public talks and posts; e.g., x.com/karpathy status 1707437820045062561 and 1723140519554105733).
- Victor, Bret. "Magic Ink: Information Software and the Graphical Interface" (2006); "Up and Down the Ladder of Abstraction" (2011); Dynamicland (ongoing). worrydream.com / dynamicland.org.

### Wanted-but-not-fully-verified

- Agha 1986 and Nii 1986 were characterized from abstracts and standard secondary summaries; full-text reads were not performed. Their roles in this review (actor semantics; blackboard control component) are uncontroversial and well-attested in secondary literature.
- The companion review `pm/docs/literature-review-user-model.md` is cited for the persona/role-prompting evidence in Appendix B §7; its own references (Salewski 2023, Deshpande 2023, Gupta 2023, the Persona Selection Model) carry that section's empirical weight.

---

## Appendix A — Claude Code feature-by-feature walk

Read this if you want the per-feature evidence behind the prior-art-in-brief Claude Code cluster. For each Claude Code feature: its relation to the plan, the hack you would need to force it into the living-artifacts role, and what the plan provides instead.

**CLAUDE.md (context files Claude reads automatically).** *Relation to the plan:* CLAUDE.md is the closest existing thing to "an artifact that carries guidance for the intelligence." *The hack:* if you tried to build a living artifact out of CLAUDE.md, you would point a machine-append process at it — and immediately corrupt its contract. CLAUDE.md is human-curated context humans expect to read and trust; a file that the system continuously rewrites is no longer that. CLAUDE.md is also one undifferentiated blob — it cannot express "this part is the task queue, this part is negotiation history." *What the plan provides:* a structured artifact with a typed task queue, negotiation history, and a self-maintenance schedule, with a clean separation between the human-auditable rendering and the machine-authored state.

**Hooks (scripts that run at fixed moments in a session).** *Relation:* hooks are how Claude Code "captures session learnings." *The hack:* a hook fires once, within one session; to make a living artifact you would need hooks to carry state forward across sessions, and the only place Claude Code auto-loads is CLAUDE.md — so you are back to the CLAUDE.md hack. *What the plan provides:* an artifact whose state *is* the cross-session substrate; the artifact lives between sessions by construction.

**Skills (packaged, on-demand instructions for task types).** *Relation:* the plan's "operation classes" — the named kinds of work a task can specialize into, such as "reformat" or "coherence-check" — are skill-shaped. *The hack:* skills are human-authored and installed; a living artifact whose self-maintenance tasks generate new operation classes has no home in Skills, because Skills carry no provenance and assume a human owns the file. The plan's automated want-inference PR has no Skills analogue at all. *What the plan provides:* operation classes that the artifact's own intelligence can generate and negotiate, with provenance, rather than a static human-authored library.

**Plugins (bundles of skills + hooks + MCP config, installed as a unit).** *Relation:* a plugin is a static install. *The hack:* you could package "the artifact protocol" as a plugin, but a plugin is configuration at rest; the living-artifacts substrate is a running system with evolving state. A plugin cannot *be* the running system. *What the plan provides:* the ongoing process and its state, which a plugin packages around but cannot contain.

**Subagents (isolated Claude instances with their own context, spawned to do a sub-task and return a result).** *Relation:* this is the closest Claude Code feature to the plan's "tasks." *The hack:* subagents are within-task and hierarchical — a parent spawns a child, the child returns, the parent decides. That is exactly the parent-decides shape the plan relocates away from. To get peer-to-peer negotiation out of subagents you would have to build a coordination layer the subagent abstraction does not provide, and route all their communication through a parent — reintroducing the central adjudicator. *What the plan provides:* tasks that are peers, that negotiate with each other by changing the shared artifact rather than messaging each other, and that persist between sessions rather than living and dying inside one parent's call.

**MCP servers (connections to external tools and data).** *Relation:* light. The plan could expose an artifact through MCP so other tools reach it. *Honest gap:* the plan does not engage MCP deeply, and should say so rather than imply it does. MCP is plumbing the plan could use, not a feature it competes with.

**Agentic search (Claude navigating the filesystem with grep/reads instead of a pre-built index).** *Relation:* pure substrate. Every task the plan runs will use agentic search to read the artifact and its surroundings. *What the plan adds here: nothing* — and the plan should say so plainly. Agentic search is a feature the plan simply consumes.

---

## Appendix B — Prior-Art Survey

This appendix holds the full system-by-system survey summarized in "Prior art in brief." It is organized into eight sections matching the plan's own topic clusters.

### B§1. Concurrency and coordination models without a central scheduler

Before trusting the plan's claim to be "a new kind of coordination," a reader should know what the old kinds were — and whether the plan's one-sentence dismissal of them is fair. The plan's claim that prior coordination systems "assumed a central scheduler or arbiter" is partly true and partly not, and this section checks it by walking the four systems the plan names.

**The actor model (Hewitt, Bishop & Steiger, 1973; Agha, 1986).** The actor model structures computation so the only kind of object is an *actor* — an independent unit with private state that communicates only by sending messages. There is no shared memory and no global clock. Carl Hewitt, Peter Bishop and Richard Steiger introduced it in 1973; Gul Agha gave it a rigorous semantics in 1986. The model is explicitly decentralized: there is no central scheduler. So the plan's "they assumed a central scheduler" is mostly wrong about actors. What the plan is right about is the other half: an actor's behavior is a fixed program. The "intelligence" of an actor is whatever a programmer wrote into it ahead of time. The plan's move is to replace that fixed program with an LLM, so the unit can interpret an unforeseen message and reason about a response. The plan should make the claim precisely: not "actors had a central scheduler" but "actors' per-unit behavior was a static program; ours is a general reasoner." This actors-as-negotiating-peers primitive is what Instance 2 draws on.

**Contract-net protocol (Smith, 1980).** The contract-net protocol is a negotiation mechanism for distributed problem-solving, published by Reid G. Smith in 1980. It works like subcontracting: a node broadcasts an *announcement*; other nodes reply with *bids*; the announcer *awards* the contract. Task allocation happens through this announce–bid–award cycle, with no master scheduler. This is the closest classical ancestor of the plan's "tasks negotiate peer-to-peer." Again the plan's "central arbiter" claim is too strong: contract-net is decentralized by design. But contract-net negotiates over *who runs a fixed task* — the task's content is settled. The plan's tasks negotiate over the *content of the proposal itself*. That is the real divergence from contract-net, and Instance 2 applies it directly.

**Blackboard systems (Hearsay-II; Erman, Hayes-Roth, Lesser & Reddy, 1980; Nii, 1986).** A blackboard system is an AI architecture organized around a shared workspace — the "blackboard" — that multiple *knowledge sources* read from and write to, coordinating through the board rather than directly. The canonical example is Hearsay-II (1971–76); Nii's 1986 survey is the standard reference. Here the plan's "central arbiter" claim lands squarely: classic blackboard systems did have a central control component that, each cycle, decided which knowledge source ran next. But the blackboard is being actively revived for LLM multi-agent systems. Han & Zhang (arXiv:2507.01701, 2025) gave the first LLM implementation of the classical blackboard — agents share messages on a board, a selection step picks who acts, rounds repeat until consensus — competitive with state-of-the-art at lower token cost. Salemi et al. (arXiv:2510.01285, 2025) apply the pattern to data discovery with 13–57% relative gains. So "blackboard" is a live 2026 research term. These revived blackboards differ from the plan in two ways: the board remains *passive* shared state — it carries no wants, spawns nothing — and neither deletes the central node (Salemi et al. retains a central agent posting requests; it removes only the capability registry). The plan's *artifact* is a blackboard, inherited from this live lineage; what the plan adds is a blackboard that is itself an agent, carrying its own wants and holding competing in-flight proposals as first-class state. This is the primitive Instance 1 draws on.

**Linda tuple spaces (Gelernter, 1985; Carriero & Gelernter, 1989, 1992).** Linda is a coordination language whose core idea is the *tuple space*: a shared, content-addressable pool of data records. Processes coordinate by posting tuples (`out`), reading them (`rd`), and atomically removing them (`in`); a process never names another process. Linda is genuinely decentralized — no scheduler. A 2025 industry essay, "Our AI Orchestration Frameworks Are Reinventing Linda" (Carvalho), argues modern LLM-agent task systems are rediscovering tuple spaces without knowing it. The plan should read this as a caution: its "live task queue" inside an artifact is, structurally, a tuple space scoped to one document — a well-understood, robust pattern, which the plan should name rather than present as novel. This is the primitive Instance 3 leans on.

**Assessing the plan's framing.** The plan's diagnosis is half right. The sentence "most of them assumed a central scheduler or arbiter" is true of classic blackboards and false for actors, contract-net, and Linda. The plan should adopt the narrower wording — "most made the per-unit intelligence small and fixed; blackboards additionally assumed a central scheduler." The *direction* of the plan's framing is unaffected, because the load-bearing half is the other one: "boxed in by determinism and programmability constraints." That clause is exactly right for all four systems — each made the per-unit intelligence small, fixed, and pre-programmed, and negotiated over scheduling or assignment, not over the content of the work. Replacing the fixed per-unit program with a general reasoner, and moving the negotiation surface onto the work's content, is the genuine shift.

### B§2. Concurrent shared state: CRDTs and operational transformation

Can many edits happen to one document at the same time without a referee deciding the order? This problem was solved decades ago, so it is not a risk the plan carries. *Syntactic* means the literal text; *semantic* means what the text means. A merge can succeed syntactically and still fail semantically.

**Operational transformation (Ellis & Gibbs, 1989).** OT is the original technique for letting multiple people edit one document at once without a central lock. Clarence Ellis and Simon Gibbs introduced it in 1989. The idea: if two people edit the same sentence at once, the system rewrites each person's edit so that, applied together, they do not clobber each other and both people see the same final sentence. OT became the engine behind Google Docs. Its guarantees — edits applied in an order respecting which came first, and every copy ending identical — are what the plan needs for "multiple in-flight tasks act on overlapping regions of the artifact simultaneously."

**Conflict-free replicated data types (Shapiro, Preguiça, Baquero & Zawirski, 2011).** A CRDT is a data structure designed so that independent copies, edited concurrently and offline, are mathematically guaranteed to converge to the same value once they exchange updates — no central coordinator, no merge conflicts. CRDTs are the modern, decentralized answer to the problem OT solved with a central server. If the plan wants in-flight task state that multiple tasks edit concurrently and that survives a restart, the off-the-shelf answer is "model the artifact, or its task queue, as a CRDT." But a CRDT answers only the *concurrent-edit* sub-question. It does not answer the harder open question: how to store in-flight, unsettled task state — proposals mid-negotiation — as first-class persistent content. MMP's CAT7 schema — a fixed seven-field form — is one point in that design space. A fixed-field schema fits *typed knowledge* but is likely wrong for *unsettled work state*, which argues for a more open representation. The prior art narrows the open question; it does not close it.

**Recent work: CRDTs for LLM agents (2025–2026).** Three recent pieces bring this lineage against the plan:

- **CodeCRDT (arXiv:2510.18893, 2025)** — multiple LLM agents generate code concurrently into a CRDT-backed shared state, coordinating by monitoring observable updates rather than message passing. This is close to the plan's no-central-arbiter model. CodeCRDT is an academic 600-trial study with no commercial deployment. Its central finding is supporting evidence for the plan: across 600 trials, parallel coordination produced up to a 21% speedup on some tasks and up to a 39% slowdown on others, and — the load-bearing number — semantic conflicts persisted in 5–10% of cases despite the CRDT guaranteeing identical copies. A CRDT guarantees the *text* merges; it does not guarantee the *meaning* is coherent. That 5–10% residual is the gap the plan's intelligence-resolved layer fills. The figure is one measurement of code-merge conflicts in a single preprint; the semantic-conflict rate for prose-and-task artifacts is unmeasured and may differ.
- **"AI agents as CRDT peers" (Electric, 2026)** — an industry write-up of treating an LLM agent as just another peer in a collaborative document built with Yjs, appearing to humans with a cursor. This is the plan's "humans and tasks are participants in the same negotiation," already shipping as a pattern.
- **"Collaborative Document Editing with Multiple Users and AI Agents" (arXiv:2509.11826, 2025)** — "the first to investigate how multiple people work together with multiple shared AI agents within a shared document environment," with agent profiles and tasks as shared objects. This is structurally the plan's "artifact contains its task queue."

The takeaway: the plan's concurrency substrate is not a research risk. OT and CRDTs are mature; the agent-on-CRDT pattern is being actively built. The plan's contribution is the semantic layer (integrity) sitting on top of a merge mechanism that already works.

### B§3. The living-document and augmentation vision

The idea of a document that is also a live, working thing is not new; this section traces it back sixty years.

**Engelbart: augmenting human intellect (1962, 1968).** Douglas Engelbart's 1962 report argued that computers should *extend* human thinking, and that the medium was a dynamic, manipulable document. His 1968 "Mother of All Demos" showed NLS: hypertext, real-time collaborative editing, revision control. The plan's commitment to keep a human-readable markdown view as a rendering of the underlying artifact is an Engelbart-lineage move: the document is the shared, auditable surface between human and machine.

**Bret Victor and Dynamicland.** Bret Victor's essays and his Dynamicland project push the augmentation vision toward media that are *alive* in the sense of continuously responsive. The plan's word "living" is in this register. The honest note: Victor's work is about *human-facing* dynamic media; the plan's artifacts are "consumed primarily by LLMs," with the human view as a rendering. The plan inherits Victor's aspiration but inverts his audience.

**Literate programming and computational notebooks.** Donald Knuth's literate programming (1984) proposed a program written as prose with code interleaved. Computational notebooks (the Jupyter lineage) are its modern mass adoption. Both are precedents for the plan's central structural move — an artifact that is simultaneously a human-readable document and a machine-actionable structure — and show the document-that-also-computes is a proven, not speculative, shape.

### B§4. LLM agents, memory, and the "LLM-OS" framing

This section covers the work that comes closest to the plan, and where its biggest claim — "no central manager" — gets tested.

**Society of Mind (Minsky, 1986).** Marvin Minsky's *The Society of Mind* proposed that intelligence emerges from many simple, individually-unintelligent "agents." It is the philosophical ancestor of every multi-agent system below. The plan's "community of living units" is a Society-of-Mind framing with one inversion: Minsky's agents are simple; the plan's units are each fully intelligent. That inversion is the plan's whole bet.

**MemGPT (Packer et al., 2023).** MemGPT treats an LLM like an operating system managing memory, shuffling information between the limited context window and external storage so an agent can hold a coherent state across a long interaction. It is a worked answer to one artifact managing its own persistent memory — relevant to the plan's "how does in-flight task state persist across pm restarts." But MemGPT persists an agent's memory, not in-flight, unsettled task state held as first-class persistent content. The prior art narrows that sub-question without closing it.

**Karpathy's "LLM-OS" framing (2023–2024).** Andrej Karpathy's framing casts the LLM as the *kernel* of a new operating system: the model is the processor, the context window is RAM, tools are peripherals. It is the vocabulary the plan's "pm becomes a renderer and host, not a state machine" is reaching for — exactly Instance 3. The cluster surveyed here — memory stores, file-centric state, skills, harness engineering — is reviewed under one frame by **"Externalization in LLM Agents" (arXiv:2604.08224, 2026)**, the umbrella reference for it.

**MAIF — an artifact-centric paradigm, already named.** The plan introduces an artifact-centric framing. That framing has a published precedent the plan must cite. **MAIF** (arXiv:2511.15097, 2025) proposes, verbatim, "an artifact-centric AI agent paradigm where behavior is driven by persistent, verifiable data artifacts rather than ephemeral tasks." So the phrase "artifact-centric AI agent paradigm" is not the plan's to claim. But MAIF is a file format for trustworthy, auditable AI data: regulatory compliance, provenance tracking, tamper detection. It has no conflict-resolution mechanism, no negotiation, no "wants," no self-maintenance. Its artifacts *prove*; they do not *act*. MAIF fuses verification; the plan fuses agency.

A 2026 position paper, **Ψ-Arch (arXiv:2604.13934)**, proposes "autopoietic architectures" — software that self-constructs and self-maintains via a foundation-model reasoning unit — but as an aspirational single-program direction, not a built system, and with no concurrency, peer negotiation, or in-flight state; the plan applies the same self-maintenance aspiration to a population of negotiating artifacts.

A 2026 data-model paper, **"Intermediate Artifacts as First-Class Citizens" (arXiv:2605.12087)**, proposes typed, versioned, dependency-aware durable intermediate artifacts — so the plan does not coin that data-model vocabulary; but its artifacts are passive completed work-products with no agency, where the plan's residual is agency over the structure plus representing in-flight proposals as superposed rather than as durable finished products.

**LSS (arXiv:2603.15690)** names "Endogenous Evolution" — behavior-shaping files the multi-agent system rewrites — so "artifacts that get rewritten" is not unprecedented; but LSS's artifacts are the medium agents rewrite, where the plan puts the agency in the artifact itself.

**AutoGen, MetaGPT, ChatDev — and the central-coordinator confrontation.** The plan's coordination model is a departure from the dominant design of current multi-agent LLM systems:

- **AutoGen** (Wu et al., 2023) is Microsoft's multi-agent conversation framework. Its "group chat" mode runs through a central "group chat manager" that decides who speaks next — a central arbiter.
- **MetaGPT** (Hong et al., 2023) encodes fixed Standard Operating Procedures — Product Manager → Architect → Engineer — pre-designed by humans.
- **ChatDev** (Qian et al., 2024) runs a fixed 7-role pipeline.
- **TheBotCompany** (arXiv:2603.25928, 2026) is the same shape: a three-phase state machine in which manager agents "dynamically hire, assign, and fire worker agents" — a manager hierarchy with central control, experimentally evaluated, not deployed. The commercial **Swarms** framework is the productized version. Both are foils for the plan, not prior art that preempts it.

So the plan is correct that the mainstream of multi-agent LLM work is orchestrator-centric or fixed-pipeline. The plan's claim is a genuine departure: it removes the system's dependence on a central manager-intelligence by relocating adjudication into the artifact substrate's own integrity-maintenance — not by eliminating adjudication. A growing cluster of recent academic work builds the decentralized alternative: AgentNet (arXiv:2504.00587) eliminates the central orchestrator, coordinating agents over an adaptive graph; SwarmSys (B§5) is another. Two things keep the plan's claim a genuine departure: deployed and commercial tools remain orchestrator-centric, and these frameworks coordinate *agents* over a graph — none builds a general self-maintaining *artifact* substrate. What is unbuilt is not decentralized coordination; it is the living artifact.

### B§5. Self-organizing and emergent coordination

This section contains the prior art closest to the plan's core claims. The closest works are academic — papers and studies, not deployed systems. Where one reports a finding that looks like a threat, the finding usually has a time dimension the plan's framing already accounts for.

**Stigmergy and swarm intelligence.** Stigmergy is indirect coordination: agents change a shared environment, and other agents respond, with no direct messaging — the textbook example is ants laying pheromone trails. In software, stigmergy looks like writing to a shared memory store or updating a task queue. The plan's artifact-with-a-task-queue, where tasks see "what other proposals are in flight nearby," is a stigmergic design; the plan should adopt the word.

**Market-based coordination.** Smith's contract-net spawned a lineage of market-based coordination: agents bid, in a simulated economy, for tasks (Dias et al., 2006, is the standard survey). The plan's "integrity as a shared constraint that emerges from negotiation" is in this family — distributed agreement through local exchanges. The plan's twist: the "currency" is integrity pressure, not price, and the bidders are LLM reasoners. Instance 4 is the most direct application.

**The integrity problem has a name in the recent literature.** The plan's "artifact integrity" construct is not un-named. **Semantic Consensus** (arXiv:2604.16339, 2026) formally treats it, defining "Semantic Intent Divergence" — cooperating LLM agents developing inconsistent interpretations of shared objectives — as a formally-unaddressed root cause of multi-agent failure, citing production failure rates of 41–86.7%. It proposes a Semantic Consensus Framework with a conflict-detection engine and a drift monitor. The plan should cite this as related work for its integrity construct. The differentiation is in *where the mechanism sits*: Semantic Consensus is process-aware middleware over the agents; the plan makes integrity a property of the artifact itself.

**Recent work: self-organizing LLM agents — the closest academic neighbors.** Several 2025–2026 papers sit close to the plan. All are academic; the differentiation is that the plan carries the architecture into a *general artifact data structure inside a working tool*.

- **SwarmSys (arXiv:2510.10047, 2025)** is "a closed-loop framework that enables LLM agents to coordinate through lightweight, pheromone-like traces ... without centralized control." The decentralized, stigmergic coordination is close to the plan's headline, but SwarmSys is a coordination architecture studied in isolation and stops at coordination. The plan's claim is that the *artifact itself* should be the unit, and that coordination is what *emerges* when artifacts of that kind interact. (The academic SwarmSys paper is a different thing from the commercial `kyegomez/swarms` framework, which is orchestration-centric — the design the plan argues against.)
- **AgentNet (arXiv:2504.00587, 2025)** is the strongest *built* instance of orchestrator-free coordination: LLM agents specialize, evolve, and route tasks over a dynamically restructured DAG with no central manager, beating centralized baselines on accuracy. Its unit, though, is the *agent*: it has no shared data structure holding in-flight unsettled state, no task lifecycle, no wants. The plan's residual — the artifact itself as the coordinating substrate and a negotiating peer — is untouched by it.
- **ScienceClaw + Infinite (arXiv:2603.14312, 2026)** — independent agents conduct scientific investigation with no central coordination; an artifact layer records lineage as a DAG, and an "autonomous mutation layer" prunes that DAG to resolve conflicting or redundant workflows. The mutation-and-pruning idea rhymes with the plan's self-maintenance. The difference: ScienceClaw's artifacts are *immutable provenance records*; the pruning is a layer operating *over* the DAG, and the agency sits in the agents. The plan's artifact carries its own wants and is itself a negotiating peer. That gap is the plan's residual.
- **AgentsNet (arXiv:2507.08616)** is a benchmark for multi-agent self-organization, scalable to 100 agents — a ready-made yardstick the plan's later PRs could measure against.
- **"Drop the Hierarchy and Roles" (arXiv:2603.28990, 2026)** is the most relevant paper for this plan — a controlled study, not a system, running 25,000+ task runs across 8 models, 4–256 agents, 8 coordination protocols, and 4 complexity levels, comparing centralized coordination, fully-autonomous self-organization, and hybrids. Its findings:
  - Groups of LLM agents given a mission and a capable model but no pre-assigned roles spontaneously invent organizational structure (5,006 distinct roles invented by just 8 agents) and exhibit *voluntary self-abstention*. This is direct empirical support for the plan's "wants"/self-organization premise.
  - A *hybrid* — fixed agent ordering, autonomous role selection — beat fully-autonomous coordination by 44% and centralized coordination by 14%. This is closer to a challenge to pure self-organization than a tuning detail: some imposed structure beats none. The honest move is to narrow the plan's wording. The plan's text describes something close to pure emergence ("proposals exist in superposition") and under-specifies how much structure it keeps. The narrowing: the plan does not eliminate adjudication — nothing could — it *relocates* it. Today the system depends on adjudicators outside the work: a human reviewer, pm's central state machine. The plan removes that dependency by internalizing adjudication into the substrate's own integrity-maintenance tasks. The integrity-maintenance task is adjudication-flavored, and that is the contribution. The human still enters — at the boundary, for work the system's own adjudication could not resolve — which is the plan's "human as boundary, not bottleneck" framing. So the plan's claim is not "no adjudicator" as an absolute; it is that the system can carry progressively more of its own integrity maintenance without the external adjudicators it relies on today. The plan's own text should drop any framing of "no central arbiter" as an absolute and state the dependency-removal claim instead.
  - Self-organization "is a privilege of strong models. Below a capability threshold ... autonomy reverses and hurts performance for weaker models."

  This last finding bears on the plan's cost-stratification idea — "demote routine specializations to cheaper intelligence." Below a capability threshold, autonomy actively reverses and hurts performance. So the honest framing of cost-stratification is as a **bet**: the capability-per-dollar curve keeps moving such that "competent enough to negotiate" becomes affordable at the routine tier — and the same study found open-source models reaching 95% of closed-source quality at 24x lower cost. The one residual: whether "near-capable on benchmark tasks" transfers to "capable enough to negotiate without degrading artifact integrity," which the study does not test. The watcher fallback — privileged participants catching a degraded proposal — is what makes the bet survivable if the curve moves slowly. The plan should cite this paper and present cost-stratification in those terms.

**Decentralized reconciliation is being built — Agora-Opt.** **"From Soliloquy to Agora" (Agora-Opt, arXiv:2604.25847, 2026)** is an agentic framework scoped to *optimization modeling*. Multiple agent teams each produce an end-to-end solution independently, reconciled through an "outcome-grounded debate protocol" scored against verifiable solver outcomes, with a read-write memory bank of solver-verified artifacts. This is decentralized, intelligence-based reconciliation of concurrent candidates with no central selector — a published instance of the plan's "intelligence resolves conflicts" thesis. It is agent-centric, not artifact-centric, and it has a solver oracle the plan's domain lacks: integrity is a soft, judgment-evaluated constraint. The plan generalizes the pattern to a self-maintaining general artifact substrate with no solver oracle; the residual survives, but the plan can no longer present decentralized intelligence-based reconciliation itself as unprecedented.

**Does the negotiation converge?** CRDT convergence is a mathematical guarantee about syntactic state. The plan's negotiation convergence — "proposals converge as they negotiate," "stalled negotiations time out into dropped" — is an empirical hope about LLM reasoning. The convergence claim should be tested with a named protocol: run N artifact-pairs through forced-conflict negotiations; dependent measures: termination rate, oscillation rate, false-consensus rate, benchmarked against the timeout rule. The boundary claim is also in tension with measured 41–86.7% multi-agent failure rates, so the honest framing is "human-at-boundary is the goal state reached as integrity-maintenance matures, not a day-one property." Whether LLM-to-LLM proposal negotiation reliably terminates is unestablished and belongs in the coverage-gaps list.

### B§6. Evolutionary computation reframed

The plan makes one ambitious side-claim: that living artifacts could change how evolutionary algorithms work. Most of it is not new.

**Classical evolutionary algorithms.** A classical evolutionary algorithm maintains a *population* of candidate solutions encoded as passive data, scores each with an external *fitness function*, and uses fitness to select which candidates reproduce. The plan's characterization — passive genomes, external fitness, external selection — is accurate.

**Open-ended evolution and novelty search.** Lehman and Stanley's **novelty search** (2011) already loosened one of the plan's three pillars: it abandons the objective fitness function, selecting purely for behavioral novelty, and outperforms objective-based search on deceptive problems. So "selection without an external fitness function" is fifteen years old.

**LLM-driven evolutionary methods (2023–2026).** The genome-as-passive-string pillar has also fallen:

- **Promptbreeder (Fernando et al., ICML 2024)** evolves a population of *prompts*, using LLM-generated mutation operators that themselves evolve. The genome is text; the mutation operator is an LLM.
- **FunSearch (Romera-Paredes et al., *Nature*, 2023)** pairs an LLM with an evaluator in an evolutionary loop, and discovered new results on the cap-set problem.
- **AlphaEvolve (Google DeepMind, 2025, arXiv:2506.13131)** is an evolutionary coding agent that improved on a 1969 matrix-multiplication result and found a data-center scheduling heuristic in production use.
- **ADAS (Hu et al., ICLR 2025)** runs a meta-agent that evolves *agentic systems themselves* from a growing archive.

A 2026 position paper, **"Agentic Evolution is the Path to Evolving LLMs" (arXiv:2602.00359)**, proposes *A-Evolve* — evolution reframed as goal-directed optimization over persistent system state. It is a fifth data point that the passive-genome and external-loop pillars are eroding, but it is single-system self-improvement, not a population of living units negotiating their own selection.

The plan's evolutionary-computation direction should be read as *inheriting from* this prior work, not competing with it. The plan does not claim that evolving prompts or programs with LLMs is new — Promptbreeder, FunSearch, AlphaEvolve and ADAS have done versions of it. Two of the classical pillars are already loosened: the genome is no longer a passive string, and selection without an external objective exists.

The one narrow element not yet present is *selection emerging from peer-to-peer negotiation among the candidates themselves* — a candidate that evaluates its own fitness in context and negotiates its survival with neighbors, rather than being scored by an external loop. In every system above, an external loop still drives selection. *Negotiated internal selection* is the unclaimed sliver. It belongs in the plan as exactly that: a narrow, long-term stretch direction the substrate makes attemptable, not a headline contribution. It is the least-evidenced part of the plan; whether negotiated selection produces useful evolutionary pressure is untested.

### B§7. Anthropomorphization as an operational prompt technique

Can you change what an AI does just by telling it to act as if a document "wanted" something? The plan bets yes. The plan states its "wants" are "a prompt scaffold, not a metaphor." The companion review `literature-review-user-model.md` covers persona and role-prompting in depth; the two findings this section relies on are quoted directly below.

- **Persona prompting demonstrably changes output.** Salewski et al.'s "In-Context Impersonation" (NeurIPS 2023) shows that prefixing a prompt with an expert persona reliably changes task performance; an expert persona beats a non-expert one across domains. This supports the plan's premise that the "wants" scaffold is operational, not decorative.
- **But the effect is double-edged and unstable.** Deshpande et al. ("Toxicity in ChatGPT," EMNLP 2023 Findings) found persona assignment can multiply toxicity sixfold; Gupta et al. (2023) found personas surface stereotypical reasoning even on neutral tasks; and the literature documents performance drops of up to 30 percentage points from *irrelevant* persona details. The plan's "wants" scaffold inherits this instability.
- **The specific framing "as if this artifact had wants" is not directly tested.** The persona literature tests personas that are *people*. The plan's move — anthropomorphizing a *non-agent* (a document) as having desires — is a specific variant with, as far as this review found, no direct empirical study. This is a coverage gap.

**Verdict for the plan.** Persona prompting is an established lever; the artifact-as-wanting variant is untested; the plan's want-inference PR should run the cheap controlled comparison — the same artifact through a "wants"-framed prompt and through a plain instruction-framed prompt asking for the same self-maintenance tasks.

### B§8. Grounding against Claude Code's current feature set

Claude Code assumes a static-config + reactive-session split with no between-sessions first-class artifact; the full feature-by-feature walk is in Appendix A. The frontier — InfiAgent (arXiv:2601.03204) and "Everything is Context" (arXiv:2512.05470) — builds the persistent file as authoritative state, but passively externalized or human-curated. The plan's residual is agency in the externalized artifact: it is the missing middle tier between Claude Code's static-config tier and its reactive-session tier — a first-class, continuously co-authored, between-sessions artifact that self-maintains rather than being passively externalized or human-curated.
