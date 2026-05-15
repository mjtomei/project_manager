# Literature Review: Living Artifacts — Data + Intelligence as the Unit

*A survey of the prior work surrounding `plan-984dfeb.md` ("Living artifacts: data + intelligence as the unit"), written for a reader evaluating whether the plan's central bet is supported by — or contradicted by — existing research.*

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
2. **No central arbiter.** Tasks negotiate peer-to-peer. Conflicts resolve against a shared constraint the plan calls *artifact integrity* — a property each task is *accountable to*, not a rule enforced from above.
3. **The human becomes a boundary, not a bottleneck.** Most work never reaches a person; humans (and "watchers" — automated supervisory processes) are *privileged participants* whose voice carries more weight, but they are still participants, not observers above the system.
4. **General intelligence removes a historical ceiling.** The plan claims earlier coordination systems — actor models, contract-net, blackboards — "gestured at this but were boxed in by determinism and programmability constraints" and "assumed a central scheduler or arbiter." It claims that putting a *generally intelligent* LLM in every unit lifts that ceiling.
5. **Where it leads.** As a stretch goal, the plan claims living units enable "a qualitatively different mode" of evolutionary computation — a community of living units rather than a population of passive strings.

This review surveys the literature each of those claims sits in. It is organized into eight sections matching the plan's own topic clusters, then a section (§9) that grounds that survey in the four concrete instances the plan commits to building in pm, then a conclusion that states — point by point — where the plan inherits from prior work, where it diverges, and where its contribution is genuinely new. A companion review, `literature-review-user-model.md`, covers persona and role-prompting in depth; Section 7 cross-references it rather than repeating it.

### What surrounds the plan

The short version, previewed here so the reader can calibrate: almost every *primitive* the plan needs already exists in a mature form. Decentralized coordination without a scheduler is fifty years old (actor model, 1973). Negotiation-by-bidding is forty-five years old (contract-net, 1980). Indirect coordination through a shared workspace is the blackboard model and Linda tuple spaces. Merging concurrent edits without a central referee is a solved problem (operational transformation, 1989; conflict-free replicated data types, 2011). The "document that is also a program" is literate programming (1984) and computational notebooks. And — most pointedly — the last twelve months have produced LLM-agent systems that are *strikingly* close to the plan's architecture: decentralized multi-agent coordination over a shared state (CodeCRDT, 2025), AI agents as peers in a conflict-free replicated document (Yjs-based agent work, 2026), and a large empirical study that directly tests "self-organizing agents vs. designed hierarchies" (the "Drop the Hierarchy" paper, 2026).

The plan's framing — "we study the prior work for inspiration and vocabulary, not as a blueprint" — turns out to be exactly the right posture. And the plan's central direction survives this survey, narrowed but intact. Stated plainly, the plan's direction is: **a data structure for artifacts that holds unsettled state as first-class — proposals in flight, not just committed content — that is relational, and that relies on intelligence to resolve conflicts between edits, or between an artifact and itself, or between an artifact and another artifact.** It is a vision people have gestured at before; what is new is that large language models make it buildable.

Two 2026 works sit closest and must be named at the outset, because the survey below is in part a response to them. The **Mesh Memory Protocol** (MMP, arXiv:2604.19540) specifies and runs a typed, semantically-merged, cross-session shared memory for LLM agents — the closest prior art on the *mechanics* the plan's substrate needs, and a candidate layer the plan could build on. **MAIF** (arXiv:2511.15097) names an "artifact-centric AI agent paradigm where behavior is driven by persistent data artifacts" — so the plan cannot claim that phrasing as unprecedented. Neither preempts the plan's actual subject: MMP coordinates *knowledge* between agents and has no concept of work, tasks, or scheduling; MAIF fuses *verification* into the data layer, not agency. The plan's subject is the layer above both — work that self-organizes through negotiation, an artifact made capable of maintaining itself. The conclusion and Section 9 state this precisely; the body sections corroborate the direction.

---

## 1. Concurrency and coordination models without a central scheduler

Before trusting the plan's claim to be "a new kind of coordination," a reader should know what the old kinds were — and whether the plan's one-sentence dismissal of them is fair. The plan's claim that prior coordination systems "assumed a central scheduler or arbiter" is *partly* true and *partly* not, and this section checks it by walking the four systems the plan names.

### The actor model (Hewitt, Bishop & Steiger, 1973; Agha, 1986)

The **actor model** is a way of structuring computation in which the only kind of object is an *actor* — an independent unit that has its own private state and communicates only by sending *messages* to other actors. There is no shared memory and no global clock; an actor reacts to a message by doing some local work, sending more messages, and possibly creating new actors. (The everyday analogy: a large office where every worker has their own desk and locked drawers, and the only way to get anything done is to send memos.)

Carl Hewitt, Peter Bishop and Richard Steiger introduced it in 1973 ("A Universal Modular ACTOR Formalism for Artificial Intelligence") and Gul Agha gave it a rigorous semantics in his 1986 book. The model is explicitly **decentralized**: there is no central scheduler. Each actor processes its own messages in its own order.

So is the plan's claim — "they assumed a central scheduler" — wrong about actors? *Mostly, yes.* The actor model never assumed one. What the plan is *right* about is the other half of its claim: actors were "boxed in by determinism and programmability constraints." An actor's behavior is a fixed program. When an actor receives a message it cannot interpret, nothing creative happens — it follows its code. The "intelligence" of an actor is whatever a programmer wrote into it ahead of time. The plan's move is to replace that fixed program with an LLM, so the unit can interpret an unforeseen message and *reason* about a response. That is a genuine difference, and the plan should make it precisely: not "actors had a central scheduler" (they didn't) but "actors' per-unit behavior was a static program; ours is a general reasoner." This actors-as-negotiating-peers primitive is what Instance 2 below draws on, where a pull request's phases become peer tasks rather than steps a state machine advances.

### Contract-net protocol (Smith, 1980)

The **contract-net protocol** is a negotiation mechanism for distributed problem-solving, published by Reid G. Smith in 1980 (*IEEE Transactions on Computers*). It works like subcontracting in business. A node with a task to delegate broadcasts an *announcement*; other nodes reply with *bids* describing how well they could do it; the announcer picks a winner and *awards* the contract. Task allocation happens through this announce–bid–award cycle, with no master scheduler deciding who does what.

This is the closest classical ancestor of the plan's "tasks negotiate peer-to-peer." Smith explicitly framed it as a "negotiation metaphor." Again the plan's "central arbiter" claim is too strong: contract-net is decentralized by design. But contract-net negotiates over *who runs a fixed task* — the task's content is settled; only its assignment is up for bid. The plan's tasks negotiate over the *content of the proposal itself*. The plan's own §"Tasks as the atom" makes exactly this point ("they treated the task's output as fixed and negotiated over scheduling. Here the task's content itself is the negotiation surface"), and it is correct. That is the real divergence from contract-net, and it is sharper than "they had a scheduler." Instance 2 below applies this directly: the implement/review/QA/merge phases of a pull request become tasks that negotiate the content of the change, not just its scheduling.

### Blackboard systems (Hearsay-II; Erman, Hayes-Roth, Lesser & Reddy, 1980; Nii, 1986)

A **blackboard system** is an AI architecture organized around a shared workspace — the "blackboard" — that multiple specialist modules (called *knowledge sources*) read from and write to. No knowledge source talks to another directly; they coordinate *through* the shared blackboard, each one watching for a state it can contribute to. The canonical example is Hearsay-II, the 1971–76 speech-understanding system (Erman, Hayes-Roth, Lesser & Reddy, *ACM Computing Surveys*, 1980). H. Penny Nii's two-part 1986 survey in *AI Magazine* is the standard reference.

Here the plan's "central arbiter" claim lands more squarely. Classic blackboard systems *did* have a central component: the **control component** (or "scheduler") that, on each cycle, looked at the whole blackboard and decided which knowledge source got to run next. Hearsay-II's control was a focus-of-attention mechanism. So blackboards are a real example of "assumed a central scheduler." The plan's relationship to blackboards is the most direct of the four: the plan's *artifact* is a blackboard (a shared workspace multiple tasks read and write), but the plan **deletes the control component** and replaces it with peer-to-peer negotiation plus the "integrity" constraint. That is a meaningful, statable inheritance-and-divergence: *the plan is a blackboard without a scheduler.* This is the primitive Instance 1 below draws on directly: the plan file becomes the shared workspace that multiple self-maintenance and user tasks read from and post to.

### Linda tuple spaces (Gelernter, 1985; Carriero & Gelernter, 1989, 1992)

**Linda** is a coordination language by David Gelernter and Nicholas Carriero (Yale, mid-1980s). Its core idea is the **tuple space**: a shared, content-addressable pool of data records ("tuples"). Processes coordinate by *posting* tuples into the pool (`out`), *reading* them (`rd`), and *atomically removing* them (`in`). A process never names another process; it just drops data into the pool, and whoever wants it picks it up by matching on content. The 1985 paper is "Generative Communication in Linda"; the 1992 *CACM* paper "Coordination Languages and Their Significance" argued that coordination is a language-design concern as fundamental as control flow.

Linda is genuinely decentralized — there is no scheduler — and it directly informs the plan's open question about the artifact's persistent representation. A 2025 industry essay, "Our AI Orchestration Frameworks Are Reinventing Linda" (Carvalho), argues that modern LLM-agent task systems — git-backed task files, SQLite task stores (SQLite is a lightweight single-file database), shared-filesystem coordination with polling — are *rediscovering* tuple spaces without knowing it. The plan should read this as a caution: its "live task queue" inside an artifact is, structurally, a tuple space scoped to one document. That is not a flaw — it is a well-understood, robust pattern — but the plan should name it as such rather than present the task queue as novel. This is the primitive Instance 3 below leans on: when pm stops being a state machine, the artifact substrate it hosts is, structurally, a tuple space — coordination through a shared pool rather than through a central orchestrator.

### Assessing the plan's framing

The plan's diagnosis of these four systems holds up; one of its two clauses does not, and the plan should fix the wording rather than keep it. The plan's sentence "most of them assumed a central scheduler or arbiter" is true of blackboard systems and false for the other three: actors, contract-net, and Linda are decentralized in the strict sense of "no master scheduler." Stated precisely, the claim that survives is narrower: *blackboard systems assumed a central scheduler; the others did not — but all four made the per-unit intelligence small and fixed.* The plan should adopt that narrower wording — for example, "most made the per-unit intelligence small and fixed; blackboards additionally assumed a central scheduler" — instead of the current sentence, which is wrong for three of the four systems it covers.

The *direction* of the plan's framing is unaffected by that fix, because the framing's load-bearing half is the other one: "boxed in by determinism and programmability constraints." That clause is exactly right for all four. Every one of these systems made the per-unit intelligence **small, fixed, and pre-programmed**, and negotiated over **scheduling or assignment, not over the content of the work**. The determinism diagnosis is the strong half and it correctly describes why these systems could only gesture at what the plan proposes to build. Replacing the fixed per-unit program with a general reasoner, and moving the negotiation surface onto the work's content, is the genuine shift, and the plan names it. So: keep the research direction; narrow the one-sentence dismissal to what is true.

---

## 2. Concurrent shared state: CRDTs and operational transformation

The plan's open questions ask, directly: "What is the artifact's persistent representation? ... CRDT-friendly for concurrent in-flight task state?" and "How does the live state of in-flight tasks persist?" This is the most technically settled area the plan touches.

### Operational transformation (Ellis & Gibbs, 1989)

**Operational transformation** (OT) is the original technique for letting multiple people edit one document at once without a central lock. Clarence Ellis and Simon Gibbs introduced it in their 1989 paper "Concurrency Control in Groupware Systems," built into the GROVE group outline editor. The idea: when two users make edits at the same time, each user's edit is *transformed* against the other's so that both arrive at the same final document. (Concretely: if you insert a word at position 5 while I delete a word at position 2, my client adjusts your insert to position 4 before applying it.) OT became the engine behind Google Docs' real-time collaboration. Its two guarantees — that edits are applied in an order respecting which edit came first (*causality preservation*), and that every copy ends up identical (*convergence*) — are exactly the guarantees the plan needs for "multiple in-flight tasks act on overlapping regions of the artifact simultaneously."

### Conflict-free replicated data types (Shapiro, Preguiça, Baquero & Zawirski, 2011)

A **conflict-free replicated data type** (CRDT) is a data structure designed so that independent copies, edited concurrently and offline, are *mathematically guaranteed* to converge to the same value once they exchange updates — with no central coordinator and no merge conflicts. Marc Shapiro, Nuno Preguiça, Carlos Baquero and Marek Zawirski formalized CRDTs in 2011 (SSS 2011, "Conflict-Free Replicated Data Types"), defining two flavors — one that syncs whole snapshots, one that syncs individual changes — and the conditions a type must satisfy. CRDTs are the modern, decentralized answer to the same problem OT solved with a central server.

This directly answers one of the plan's open questions. If the plan wants in-flight task state that multiple tasks edit concurrently and that survives a restart, the off-the-shelf answer is "model the artifact, or its task queue, as a CRDT." The plan does not need to invent this; it needs to *adopt* it.

### Recent work: CRDTs for LLM agents (2025–2026)

Three very recent pieces of work bring this lineage right up against the plan:

- **CodeCRDT (arXiv:2510.18893, 2025)** — "Observation-Driven Coordination for Multi-Agent LLM Code Generation." Multiple LLM agents generate code concurrently into a CRDT-backed shared state. Crucially, the coordination is **decentralized and observation-driven**: "agents coordinate by monitoring a shared state with observable updates and deterministic convergence, rather than through explicit message passing" — *convergence* being the guarantee that all copies, however independently edited, end up identical. This is *very close* to the plan's no-central-arbiter model, and it is close to a blackboard too. CodeCRDT is an academic study — a 600-trial evaluation on arXiv, with no commercial or real-world deployment — and it does one thing: CRDT-plus-LLM coordination for *code-merge specifically*. Its central empirical finding is, for the plan, **supporting evidence rather than a competing claim**. Across 600 trials, parallel coordination produced up to a 21% speedup on some tasks but up to a 39% slowdown on others, and — the load-bearing number — semantic (meaning-level, not syntactic) conflicts persisted in 5–10% of cases *despite perfect CRDT convergence*. A CRDT guarantees the *text* merges; it does not guarantee the *meaning* is coherent. That 5–10% residual is exactly the gap the plan's "intelligence resolves conflicts" thesis is built to fill: a separate research group, working independently on a narrower slice, has now measured the precise size of the hole that the plan's intelligence-resolved layer is designed to close. CodeCRDT does not preempt the plan's contribution — it supplies the empirical motivation for it.
- **"AI agents as CRDT peers" (Electric, 2026)** — an industry write-up of treating an LLM agent as just another peer in a Yjs (a popular CRDT library) collaborative document, appearing to humans with a cursor like any other collaborator. This is the plan's "humans and tasks are participants in the same negotiation" — already shipping as a pattern.
- **"Collaborative Document Editing with Multiple Users and AI Agents" (arXiv:2509.11826, 2025)** — describes itself as "the first to investigate how multiple people work together with multiple shared AI agents within a shared document environment," with agent profiles and tasks as shared objects in the document. This is structurally the plan's "artifact contains its task queue."

The takeaway for Section 2: the plan's concurrency substrate is not a research risk. OT and CRDTs are mature; the agent-on-CRDT pattern is being actively built. The plan's contribution is *not* the merge mechanism — it is the **semantic** layer (integrity) sitting on top of a merge mechanism that already works.

---

## 3. The living-document and augmentation vision

The idea of a document that is also a live, working thing is not new. This section traces it back sixty years, so the plan's "living artifact" — "a structured object ... text-renderable, that humans can audit" — can be judged against what was already tried.

### Engelbart: augmenting human intellect (1962, 1968)

Douglas Engelbart's 1962 report "Augmenting Human Intellect: A Conceptual Framework" argued that computers should *extend* human thinking rather than replace it, and that the medium for this was a dynamic, manipulable document. His 1968 live demonstration — "The Mother of All Demos" — showed the NLS ("oN-Line System"): hypertext, real-time collaborative editing of a shared document, and revision control, all decades before they were common. The plan's "keep the human-readable markdown view as a rendering of the underlying artifact, so humans can still read and edit by hand" is an Engelbart-lineage commitment: the document is the shared, auditable surface between human and machine.

### Bret Victor and Dynamicland

Bret Victor's essays — "Magic Ink" (information software design) and "Up and Down the Ladder of Abstraction" (thinking explicitly across levels of representation) — and his current project, **Dynamicland** (a physical space that is itself a communal computer), push the augmentation vision toward media that are *alive* in the sense of continuously responsive. The plan's word "living" is in this register. The honest note: Victor's work is about *human-facing* dynamic media — making representations a person can see and feel. The plan's artifacts are "consumed primarily by LLMs," with the human view as a rendering. So the plan inherits Victor's *aspiration* (artifacts that are responsive, not inert) but inverts his *audience* (machine-primary, human-auditable). Worth stating, so the inheritance is not overclaimed.

### Literate programming and computational notebooks

Donald Knuth's **literate programming** (1984, *The Computer Journal*) proposed that a program should be written as a prose explanation with code interleaved, from which both human documentation and compilable code are extracted. **Computational notebooks** (the Jupyter lineage) are the modern mass-adoption of this idea: a single document that mixes prose, code, and live computed output. Both are precedents for the plan's central structural move — an artifact that is *simultaneously* a human-readable document and a machine-actionable structure. The plan's "data structure for LLM consumption ... but still text-renderable" is a literate-programming-shaped object. This lineage is worth citing because it shows the document-that-also-computes is a proven, not speculative, shape.

---

## 4. LLM agents, memory, and the "LLM-OS" framing

This is where the plan's prior art is most recent and most directly competitive.

### Society of Mind (Minsky, 1986)

Marvin Minsky's *The Society of Mind* (1986) proposed that intelligence emerges from many simple, individually-unintelligent "agents" working together — "the power of intelligence stems from our vast diversity, not from any single, perfect principle." It is the philosophical ancestor of every multi-agent system below. The plan's "community of living units" is a Society-of-Mind framing, with one inversion: Minsky's agents are *simple*; the plan's units are each *fully* intelligent. That inversion is the plan's whole bet, and it is worth stating against Minsky explicitly.

### MemGPT (Packer et al., 2023)

**MemGPT** ("Towards LLMs as Operating Systems," arXiv:2310.08560) treats an LLM like an operating system managing memory: it shuffles information between the limited context window ("main memory") and external storage ("disk"), so an agent can hold a coherent state across a long interaction. It is directly relevant to the plan's open question "How does the live state of in-flight tasks persist across pm restarts?" MemGPT is a worked answer to *one* artifact managing its own persistent memory. The plan needs that capability per artifact; MemGPT shows it is feasible and names the OS-memory metaphor for it.

### Karpathy's "LLM-OS" framing (2023–2024)

Andrej Karpathy's widely-circulated framing casts the LLM as the *kernel* of a new kind of operating system: the model is the processor, the context window is RAM, tools and retrieval are peripherals. It is a framing, not a system, but it is the vocabulary the plan's "pm becomes a renderer and a host for the artifacts, not a state machine" is reaching for. The plan's eventual milestone ("pm's orchestration is the artifact protocol") is an LLM-OS-shaped claim: the *substrate* is intelligent, and the tool around it is thin. This is exactly Instance 3 below — pm reduced to a renderer and host, with no central state machine left.

### MAIF — an artifact-centric paradigm, already named

The plan introduces an artifact-centric framing: make a persistent data artifact, not an ephemeral task, the unit that drives agent behavior. That framing has a published precedent the plan must cite. **MAIF** ("Enforcing AI Trust and Provenance with an Artifact-Centric Agentic Paradigm," arXiv:2511.15097, 2025) proposes, verbatim, "an artifact-centric AI agent paradigm where behavior is driven by persistent, verifiable data artifacts rather than ephemeral tasks." So the *phrase* "artifact-centric AI agent paradigm" is not the plan's to claim as unprecedented, and the plan should drop any implication that no one has proposed artifact-centric AI.

But MAIF and the plan put a different *kind* of intelligence into the data layer. MAIF is a file format — the Multimodal Artifact File Format — for *trustworthy, auditable* AI data: its purpose is regulatory compliance (it names the EU AI Act), provenance tracking, tamper detection. Its "active trust enforcement" means the artifact carries cryptographic provenance and access controls so every operation is auditable. MAIF has no conflict-resolution mechanism, no peer-to-peer negotiation between artifacts, no "wants," no self-maintenance tasks. Its artifacts *prove*; they do not *act*. MAIF's "production-ready implementation" is a throughput-benchmark claim — it reports streaming at 2,720.7 MB/s — not a deployed-with-real-users claim. The plan fuses a different thing into the data layer: agency. MAIF fuses verification; the plan fuses negotiation, wants, and self-maintenance. The framing is shared; the substance is not.

### AutoGen, MetaGPT, ChatDev — and the central-coordinator confrontation

The plan claims "no central arbiter, peer-to-peer negotiation." This is a **strong claim against the dominant design** of current multi-agent LLM systems, and the plan should confront it head-on:

- **AutoGen** (Wu et al., 2023, arXiv:2308.08155) is Microsoft's multi-agent conversation framework. Its "group chat" mode — which sounds the most peer-to-peer — in fact runs through a **group chat manager**: a component that "broadcasts messages and decides who the next speaker will be." That is a central arbiter. AutoGen's peer-to-peer appearance is mediated by a scheduler.
- **MetaGPT** (Hong et al., 2023, arXiv:2308.00352) encodes fixed **Standard Operating Procedures** — Product Manager → Architect → Engineer — into the agent pipeline. The roles and their order are pre-designed by humans.
- **ChatDev** (Qian et al., ACL 2024) runs a fixed 7-role pipeline (CEO → CPO → CTO → Programmer → Reviewer → Tester → Designer).
- **TheBotCompany** (arXiv:2603.25928, 2026) is a contemporary example of the same shape: an open-source orchestration framework for continuous software development, built on a three-phase state machine in which manager agents "dynamically hire, assign, and fire worker agents." It is a manager hierarchy with central control — and it is experimentally evaluated on real-world projects, not deployed. The commercial **Swarms** framework (`kyegomez/swarms`, swarms.ai), which markets "enterprise-grade multi-agent orchestration," is the productized version of the same central-coordinator design. Both are foils for the plan, not prior art that preempts it: they are instances of the orchestration-centric design the living-artifacts plan is a deliberate alternative to.

So the plan is correct that the *mainstream* of multi-agent LLM work — and the commercial products built on it — is orchestrator-centric or fixed-pipeline. Stated precisely, the plan's "no central arbiter" claim is a genuine departure from this dominant design *at the level of who adjudicates* — it removes the manager-intelligence, not necessarily every structural prior (Section 5 returns to this distinction, which matters). A small cluster of very recent academic work has begun probing the decentralized alternative (Section 5 covers it), which corroborates the plan's direction — but those are isolated demonstrations, not built substrates, and the orchestrator-centric design still owns the deployed tools. The plan keeps its research direction here; Section 5 shows where the academic frontier is testing the same bet, and where the framing needs the narrower "no central adjudicator" wording to be exactly true.

---

## 5. Self-organizing and emergent coordination

This section contains the prior art closest to the plan's core claims. Two things should be said at the outset, because they shape how the rest of the section reads. First: the closest works here are academic — papers and studies, not deployed systems. They corroborate the plan's direction; they do not build the general artifact substrate the plan specifies. Second: where one of these papers reports a finding that looks like a threat to the plan, the finding usually has a time dimension the plan's framing already accounts for. The section flags both as it goes.

### Stigmergy and swarm intelligence

**Stigmergy** is indirect coordination: agents change a shared environment, and other agents respond to those changes, with no direct messaging — the textbook example is ants laying pheromone trails. In software, stigmergy "looks like writing to a shared memory store, updating a task queue, or flagging states in a vector database" — a vector database being a store that indexes data by meaning-similarity rather than exact match. The plan's artifact-with-a-task-queue, where tasks see "what other proposals are in flight nearby," is a **stigmergic** design: tasks coordinate by reading and writing the shared artifact, not by addressing each other. The plan should adopt this word — it is the precise term for what it is doing.

### Market-based coordination

Smith's contract-net (Section 1) spawned a large lineage of **market-based coordination**: agents bid, in a simulated economy, for tasks. Dias, Zlot, Kalra & Stentz's survey "Market-Based Multirobot Coordination" (*Proceedings of the IEEE*, 2006) is the standard reference. It is relevant because the plan's "integrity as a shared constraint that emerges from negotiation, not enforcement" is in this family — distributed agreement reached through local exchanges rather than central decree. The plan's twist is that the "currency" is not price but *integrity pressure*, and the bidders are LLM reasoners rather than cost functions. Instance 4 below — code units negotiating optimizations peer-to-peer with no central profiler — is the most direct application of this market-based, decentralized-coordination lineage.

### The integrity problem has a name in the recent literature

The plan's "artifact integrity" construct — the concern that an artifact stops cohering when concurrent tasks pull it in inconsistent directions — is not un-named in the literature, and the plan should cite the work that names it. **Semantic Consensus** ("Process-Aware Conflict Detection and Resolution for Enterprise Multi-Agent LLM Systems," arXiv:2604.16339, 2026) formally treats exactly this problem. It defines "Semantic Intent Divergence" — cooperating LLM agents developing inconsistent interpretations of shared objectives because of siloed context — as a formally-unaddressed root cause of multi-agent failure, citing production failure rates between 41% and 86.7%. It proposes a Semantic Consensus Framework with a conflict-detection engine and a drift monitor. This is related work for the plan's integrity construct, and it should be cited as such: it both names the coherence-of-concurrent-intent problem formally and proposes a detection-and-resolution mechanism. The differentiation is in *where the mechanism sits*: Semantic Consensus is process-aware middleware layered over the agents; the plan makes integrity a property of the artifact itself, a shared constraint every negotiating task is accountable to. But the plan can no longer present the semantic-coherence-of-concurrent-edits problem as unnamed — Semantic Consensus names it.

### Recent work: self-organizing LLM agents — the closest academic neighbors

Two 2025–2026 papers sit close to the plan. Both are academic; the differentiation, in each case, is not "the plan did it first" — it is that the plan carries the architecture into a *general artifact data structure inside a working tool*, where these works demonstrated a piece of it on a narrower slice.

- **SwarmSys (arXiv:2510.10047, 2025)** is "a closed-loop framework that enables LLM agents to coordinate through lightweight, pheromone-like traces ... fostering self-organized collaboration ... *without centralized control*." The decentralized, stigmergic coordination is close to the plan's headline. But SwarmSys is **a coordination architecture studied in isolation** — an academic framework, with no commercial or real-world deployment — and it stops at coordination. The plan's claim is not "decentralized coordination is possible" (SwarmSys already shows that); it is that the *artifact itself* should be the unit — a data structure carrying content, in-flight proposals, negotiation history, and self-maintenance — and that coordination is what *emerges* when artifacts of that kind interact. SwarmSys corroborates that the coordination layer works; it does not specify or build the artifact substrate.

  *A note on a naming collision worth being precise about.* The academic **SwarmSys** paper is a different thing from the commercial framework called **Swarms** (the `kyegomez/swarms` project, swarms.ai), which markets itself as "enterprise-grade multi-agent orchestration." This review does not conflate them. The commercial Swarms product is *orchestration-centric* — it places a coordinating layer above the agents — which is precisely the design the living-artifacts plan argues against (no central arbiter; coordination emerges from the units, it is not imposed on them). The commercial product in this space, then, is not prior art that preempts the plan; it is an instance of the design the plan is a deliberate alternative to.

- **"Drop the Hierarchy and Roles: How Self-Organizing LLM Agents Outperform Designed Structures" (arXiv:2603.28990, 2026)** is the most relevant paper for this plan. It is a 2026 arXiv study — **a controlled study, not a system**, and not deployed anywhere. It runs **25,000+ task runs** across 8 models, 4–256 agents, 8 coordination protocols, and 4 complexity levels, directly comparing centralized coordination, fully-autonomous self-organization, and hybrids. Its findings bear directly on the plan's bets:
  - Groups of LLM agents given a mission, a communication protocol, and a capable model — **but no pre-assigned roles** — spontaneously invent organizational structure (5,006 unique roles emerged from 8 agents) and exhibit *voluntary self-abstention* (an agent withdraws from a task outside its competence). This is direct empirical support for the plan's "wants"/self-organization premise.
  - A *hybrid* — fixed agent ordering, autonomous role selection — beat fully-autonomous coordination by 44% and centralized coordination by 14%. This finding is closer to a challenge to *pure* self-organization than a tuning detail: fully-autonomous coordination underperformed the structured hybrid by a wide margin, so the empirical result says plainly that *some* imposed structure beats none. The honest move here is not to certify the plan's existing wording as surviving, but to narrow it. The plan's text describes something close to pure emergence ("there is no point in time when the edit is being reviewed"; "proposals exist in superposition"), and as written it under-specifies how much structure it keeps. The defensible position is the narrower one: the plan's commitment should be "no central *adjudicator*" — no manager-intelligence sits above the artifact deciding outcomes — not "no structure of any kind." Fixed ordering is a structural prior, not an adjudicator; the plan's privileged-participant gradient is itself a deliberate, non-flat structure. So the *direction* (coordination without a manager) holds and is empirically corroborated; but the plan's own text should adopt the "no central adjudicator" wording rather than imply pure structurelessness, which this study finds underperforms.
  - And: self-organization "is a privilege of strong models. Below a capability threshold ... autonomy reverses and hurts performance for weaker models."

This last finding bears directly on the plan's cost-stratification idea (§"Privileged participants" — "demote routine specializations to cheaper intelligence"). It should be engaged as economics, not waved away. The finding is not merely "cheap models can't self-organize *yet*"; it is that below a capability threshold, autonomy *actively reverses and hurts* performance — a cheap task's autonomous negotiation can produce output worse than a structured baseline would. So the honest framing of the plan's cost-stratification is as a **bet**, with an explicit hedge.

The bet: the capability-per-dollar curve keeps moving — the same trajectory that turned every previous frontier model into a routine, low-cost tier within a few years — such that "competent enough to negotiate" becomes affordable at the routine tier. If that holds, the plan staffs routine specializations with cheap intelligence as the curve reaches them. This is plausible but it is not a settled fact; the rate at which the self-organization floor descends, relative to the rate at which routine-tier cost buys capability, is genuinely uncertain, and "Drop the Hierarchy" supplies no guarantee about it.

The hedge: the plan's privileged-participant safety net — humans, watchers, integrity-maintenance tasks — is what makes the bet survivable if the curve moves slower than hoped. If a cheap task negotiates badly, privileged participants catch the degraded proposal. The honest qualification, which the plan should state rather than skip: that safety net answers the *safety* question (bad output is caught) but not fully the *economics* question — if the floor descends slowly, watchers may spend their time redoing a steady stream of cheap-tier proposals, which is a throughput-and-cost cost the bet has to absorb. So the correct reading of the threshold finding is not "cost-stratification is unsafe" and not "cost-stratification is correctly staged" — it is "cost-stratification is a bet on a moving cost curve, with the privileged-participant net as the hedge, and the economics of the interim is a real open risk." The plan should cite this paper and present cost-stratification in exactly those terms.

---

## 6. Evolutionary computation reframed

The plan's "Where this leads" section claims living units enable "a qualitatively different mode" of evolutionary algorithms — "the population is a community of living units, not a population of strings," with selection emerging from negotiation rather than an external fitness function. This section assesses whether that claim holds.

### Classical evolutionary algorithms

A classical **evolutionary algorithm** (EA) maintains a *population* of candidate solutions encoded as passive data ("genomes," often strings or vectors), scores each with an external **fitness function**, and uses fitness to select which candidates reproduce (with mutation and recombination). The plan's characterization — passive genomes, external fitness, external selection — is accurate.

### Open-ended evolution and novelty search

Joel Lehman and Kenneth Stanley's **novelty search** ("Abandoning Objectives: Evolution Through the Search for Novelty Alone," *Evolutionary Computation*, 2011) already loosened one of the plan's three pillars: it *abandons the objective fitness function*, selecting purely for behavioral novelty, and outperforms objective-based search on deceptive problems. So "selection without an external fitness function" is not new — it is fifteen years old. The plan's claim must be narrower than "selection without an external fitness function."

### LLM-driven evolutionary methods (2023–2026)

The genome-as-passive-string pillar has also already fallen:

- **Promptbreeder (Fernando et al., ICML 2024)** evolves a population of *prompts*, using LLM-generated mutation operators that themselves evolve — "self-referential self-improvement." The genome is text; the mutation operator is an LLM.
- **FunSearch (Romera-Paredes et al., *Nature*, 2023)** pairs an LLM (proposes programs) with an evaluator (scores them) in an evolutionary loop, and discovered new results on the cap-set problem.
- **AlphaEvolve (Google DeepMind, 2025, arXiv:2506.13131)** is an evolutionary coding agent that improved on Strassen's 1969 matrix-multiplication algorithm and found a data-center scheduling heuristic in production use.
- **ADAS — "Automated Design of Agentic Systems" (Hu et al., ICLR 2025, arXiv:2408.08435)** runs a meta-agent that evolves *agentic systems themselves*, "code as the design language," from a growing archive.

This is well-established prior work, and the plan's evolutionary-computation direction should be read as *inheriting from it*, not competing with it. The plan does not claim that evolving prompts or programs with LLMs is new — Promptbreeder, FunSearch, AlphaEvolve and ADAS have all done versions of it, and the plan's "where this leads" section is explicitly a long-term direction the substrate *enables*, building on this lineage rather than displacing it. Two of the classical pillars the plan's framing names are already loosened in this prior work: the genome is no longer a passive string (Promptbreeder and ADAS manipulate code and text with LLMs), and selection without an external objective exists (novelty search). The plan should cite all of this as the foundation its EA direction stands on.

The one narrow element not yet present in the surveyed work is *selection emerging from peer-to-peer negotiation among the candidates themselves* — a candidate that evaluates its own fitness in context and negotiates its survival with neighbors, rather than being scored by an external loop. In every system above, an external loop still drives selection: FunSearch's evaluator, AlphaEvolve's automated evaluators, ADAS's meta-agent, Promptbreeder's fitness on a training set. *Negotiated internal selection* — selection as an emergent property of the units' own negotiation — is the unclaimed sliver. It belongs in the plan as exactly that: a narrow, long-term stretch direction the substrate makes attemptable, not a headline contribution. It is the least-evidenced part of the plan, and whether negotiated selection produces useful evolutionary pressure is entirely untested. The plan should keep it small and honest, and let it stand as a direction rather than a claim.

---

## 7. Anthropomorphization as an operational prompt technique

The plan states its "wants" are "a prompt scaffold, not a metaphor": prompting an LLM to reason *as if* an artifact had wants is meant to measurably shape its output. The companion review `literature-review-user-model.md` covers persona and role-prompting in depth (its §2, "Persona, role, and framing effects on performance," and its treatment of the Persona Selection Model); this section cross-references it and addresses only the question specific to this plan: *does prompting an LLM to reason "as if X had wants" change its output, and has anyone tested it?*

The relevant evidence, from the companion review and from the persona-prompting literature it surveys:

- **Persona prompting demonstrably changes output.** Salewski et al.'s "In-Context Impersonation" (NeurIPS 2023) shows that prefixing a prompt with an expert persona reliably changes task performance; an expert persona beats a non-expert one across domains. So "telling the model to reason as a particular kind of entity" is an established, measurable lever — this supports the plan's premise that the "wants" scaffold is operational, not decorative.
- **But the effect is double-edged and unstable.** Deshpande et al. ("Toxicity in ChatGPT," EMNLP 2023 Findings) found persona assignment can multiply toxicity sixfold; Gupta et al. ("Bias Runs Deep," 2023) found personas surface stereotypical reasoning even on neutral tasks; and the persona-prompting literature documents performance drops of *up to 30 percentage points* from *irrelevant* persona details. The plan's "wants" scaffold is a persona-shaped intervention and inherits this instability: framing an artifact as wanting things will change the LLM's reasoning in ways that are not all benign and not fully predictable.
- **The specific framing "as if this artifact had wants" is not directly tested.** The persona literature tests personas that are *people* (an expert, a child, a demographic group). The plan's move — anthropomorphizing a *non-agent* (a document) as having desires — is a specific variant with, as far as this review found, **no direct empirical study**. This is a genuine coverage gap. The closest analogue is "object personas" in design and social simulation, but nothing in the surveyed literature measures whether "reason as if this plan file wanted its PRs coherent" changes an LLM's output relative to a non-anthropomorphic instruction ("check that the PRs are coherent with the plan's motivation").

**Verdict for the plan.** The plan's framing — that the "wants" scaffold is operational, a prompt-shaping intervention with teeth rather than a metaphor for the reader's benefit — is the right framing, and the literature supports it. Persona prompting is an established, measurable lever on LLM output; "tell the model to reason as a particular kind of entity, and the reasoning changes" is not in dispute. The plan's "wants" scaffold is a persona-shaped intervention, so the baseline expectation, grounded in the surveyed work, is that it *does* shape the tasks an artifact produces. The one honest qualification is scope: the persona literature tests personas that are *people*, and the specific variant of anthropomorphizing a *non-agent* — a document — as having desires has no direct empirical study this review located. That is a coverage gap, not a reason to weaken the framing. The plan's want-inference PR should run the obvious controlled comparison — the same artifact through a "wants"-framed prompt and through a plain instruction-framed prompt asking for the same self-maintenance tasks — as the natural first measurement that *confirms* the framing on its specific case, and as a check on the double-edged instability persona prompting is known to carry. The plan asserts the framing has teeth; the literature says that is the right bet, and here is the cheap experiment that nails it down.

---

## 8. Grounding: the living-artifacts model versus Claude Code's current feature set

This section is load-bearing. The plan owner specifically asked for it: a sober, feature-by-feature comparison against the most widely-used tool in this space, so the plan reads as grounded analysis rather than a flashy demo. The source is the Claude Code large-codebase best-practices blog post (claude.com), and a companion analysis — the Cycle 6 regression addendum — which worked out the same abstraction gap for a different plan and reached a conclusion this plan should adopt.

A few terms first: **Claude Code** is Anthropic's command-line coding tool; pm is built on top of it (every task the plan runs ultimately spawns a Claude Code session). **CLAUDE.md** is a project-context file Claude Code reads at the start of every session. The other features are glossed inline below.

The companion addendum's core finding, which this section confirms and extends: **Claude Code's feature set assumes a static-config + reactive-session split.** Configuration (CLAUDE.md, skills, plugins) is human-authored and reviewed every "three to six months." Sessions are reactive — a human prompts, Claude acts, the session ends. There is **no abstraction in Claude Code for an artifact that is continuously co-authored and lives between sessions as first-class state.** The living-artifacts plan *is* that missing abstraction, made the explicit subject. Feature by feature:

**CLAUDE.md (context files Claude reads automatically).** *Relation to the plan:* CLAUDE.md is the closest existing thing to "an artifact that carries guidance for the intelligence." *The hack:* if you tried to build a living artifact out of CLAUDE.md, you would point a machine-append process at it — and immediately corrupt its contract. CLAUDE.md is *human-curated context humans expect to read and trust*; a file that the system continuously rewrites is no longer that. CLAUDE.md is also one undifferentiated blob — it cannot express "this part is the task queue, this part is negotiation history." *What the plan provides that CLAUDE.md can't:* a structured artifact with a typed task queue, negotiation history, and a self-maintenance schedule, with a clean separation between the human-auditable rendering and the machine-authored state.

**Hooks (scripts that run at fixed moments in a session).** *Relation:* hooks are how Claude Code "captures session learnings." *The hack:* a hook fires *once*, within *one* session; to make a living artifact you would need hooks to carry state forward across sessions, and the only place Claude Code auto-loads is CLAUDE.md — so you are back to the CLAUDE.md hack. *What the plan provides:* an artifact whose state *is* the cross-session substrate; the artifact lives between sessions by construction, not by a hook smuggling state into a config file.

**Skills (packaged, on-demand instructions for task types).** *Relation:* the plan's "operation classes" — the named kinds of work a task can specialize into, such as "reformat" or "coherence-check" — that a task picks up during specialization are skill-shaped: packaged vocabulary for a kind of work. *The hack:* skills are *human-authored and installed*; a living artifact whose self-maintenance tasks generate new operation classes has no home in Skills, because Skills carry no provenance ("which run authored this") and assume a human owns the file. The plan's *automated want-inference* PR — where the system synthesizes its own self-maintenance behavior — has no Skills analogue at all. *What the plan provides:* operation classes that the artifact's own intelligence can generate and negotiate, with provenance, rather than a static human-authored library.

**Plugins (bundles of skills + hooks + MCP config, installed as a unit).** *Relation:* a plugin is a static install. *The hack:* you could package "the artifact protocol" as a plugin, but a plugin is *configuration at rest*; the living-artifacts substrate is *a running system with evolving state* (in-flight tasks, negotiation histories). A plugin cannot *be* the running system. *What the plan provides:* the ongoing process and its state, which a plugin packages around but cannot contain.

**Subagents (isolated Claude instances with their own context, spawned to do a sub-task and return a result).** *Relation:* this is the closest Claude Code feature to the plan's "tasks." *The hack:* subagents are *within-task and hierarchical* — a parent spawns a child, the child returns, the parent decides. That is exactly the central-arbiter shape the plan rejects. To get peer-to-peer negotiation out of subagents you would have to build a coordination layer the subagent abstraction does not provide, and route all their communication through a parent — reintroducing the arbiter. *What the plan provides:* tasks that are peers, that negotiate with each other directly (stigmergically, through the shared artifact), and that persist between sessions rather than living and dying inside one parent's call.

**MCP servers (connections to external tools and data).** *Relation:* light. The plan could expose an artifact through MCP so other tools reach it. *Honest gap:* the plan does not engage MCP deeply, and should say so rather than imply it does. MCP is plumbing the plan *could* use, not a feature it competes with.

**Agentic search (Claude navigating the filesystem with grep/reads instead of a pre-built index).** *Relation:* pure substrate. Every task the plan runs will use agentic search to read the artifact and its surroundings. *What the plan adds here: nothing* — and the plan should say so plainly. Not every Claude Code feature is a contribution surface; agentic search is one the plan simply consumes.

**Plan mode (Claude proposes a plan and waits for human approval before acting).** *Relation:* plan mode is the *reactive, human-gated* version of what the plan wants to make *continuous and mostly un-gated*. In plan mode, the plan is a transient artifact inside one session, and the human approves it once. *The hack:* you could imagine re-entering plan mode repeatedly to simulate a living plan, but each entry is a fresh, stateless proposal — there is no carried-forward negotiation history, no in-flight tasks, no self-maintenance. *What the plan provides:* the plan-as-artifact *persists*, accretes negotiation history, and runs its own self-maintenance between human touches — the human is a boundary the plan occasionally crosses, not a gate every proposal stops at.

**The agent-manager role.** The blog post names an emerging "agent manager" — a hybrid PM/engineer who curates configuration, owns the plugin marketplace and CLAUDE.md conventions. This is the closest the blog comes to the plan's thesis, and the contrast is exact: the agent manager is *a human who curates static config on a 3–6-month cadence*. The plan's privileged-participant model replaces that with *a human who participates in negotiations where they happen to show up* — the curation is continuous and mostly automated (self-maintenance tasks, want-inference), and the human's role shrinks to the boundary cases. The plan is, precisely, "the agent-manager role, made continuous and largely automated."

**Scoping, both directions.** The blog post names real Claude Code limitations — codebases with hundreds of thousands of folders, non-git version control. The plan **inherits** these; it does not address them. And the plan does not *replace* any Claude Code feature — it builds a layer *on top of* the reactive session and *beside* the static config, occupying the gap between them. The plan's contribution, stated in the blog's own vocabulary: **Claude Code has a static-config tier and a reactive-session tier and nothing in between; the living-artifacts plan is the missing middle tier — a first-class, continuously co-authored, between-sessions artifact.** That is concrete, it is grounded in the current tool, and it is not a demo.

---

## 9. The plan's instances, grounded in pm

Section 8 grounded the plan against the tool people use *today* — Claude Code. This section grounds it against the tool the plan actually changes — pm itself. The two are complementary: §8 is the *external* comparison (against the dominant tool in the field); this section is the *internal* one (against pm's own current design). The prior-work survey, Sections 1–7, supplied a vocabulary — blackboard, actor, tuple space, market coordination. This section spends that vocabulary on the four concrete things the plan commits to building, in the order the plan builds them. For each: what pm does today and where that hurts; what the living-artifact version changes; what new way of working it unlocks; and which cluster of prior work it draws on.

A reminder of two pm terms used throughout, glossed for a reader who has not used the tool: a **plan** is a markdown file (under `plans/`) that lays out a body of intended work as a list of pull requests; **`project.yaml`** is pm's single bookkeeping file, tracking every plan and pull request and its current status. A **watcher** is an automated supervisory process pm runs in the background — it polls for a condition (a stuck pull request, say) and acts when it sees one.

### Instance 1 — plan files become living artifacts

**pm today.** A plan is static markdown (`plans/*.md`) plus a one-line entry in `project.yaml`. Keeping that plan coherent — auditing that its pull requests still depend on each other sensibly, checking that the narrative still flows, noticing when a pull request has quietly drifted from the plan's stated motivation — is manual work. A human does it, or runs a dedicated "plan-review" session to do it. The adversarial-review effort that produced *this very literature review* is an instance of the pain: across several cycles, a human kept noticing the plan and its documents drifting apart and kept prompting coherence fixes by hand. Nothing in pm spots that drift on its own.

**Living-artifact version.** The plan stops being inert text. It carries its own task queue and its own self-maintenance schedule. The coherence-check is no longer a thing a human remembers to run — it becomes a self-maintenance task the plan artifact spawns from its own "wants" (the plan, framed as wanting its pull requests to stay coherent with its motivation, generates the check as work).

**What it enables.** The plan notices its own staleness. When a pull request's description drifts from the plan's motivation, that surfaces as a negotiation between the drifting pull request and the plan's maintenance task — immediately — rather than waiting for the next time a human sits down for a plan-review session. The hand-run coherence loop becomes a standing property of the artifact. The adversarial-review cycle above is the concrete before-and-after: what a human did by repeated prompting becomes something the plan does for itself.

**Prior-work cluster it draws on.** Blackboard systems (Section 1) — the plan is a shared workspace that multiple tasks read from and post to. Engelbart and Victor (Section 3) — the requirement that the plan stay markdown-renderable, so a human can still read and audit it by hand, is the augmentation lineage's human-readable-surface commitment.

### Instance 2 — PRs become living artifacts

**pm today.** A pull request's specification is markdown. The flow that carries it from implementation through review, testing, and merge is pm orchestration code — a state machine that watches each pull request's status and advances it one step at a time. When a pull request gets stuck (its testing phase keeps failing), an external bug-fix watcher detects the impasse from outside, by pattern-matching repeated failure. The pull request itself is mute; something else has to notice it is in trouble.

**Living-artifact version.** The pull request's specification *is* the document; the implementation, review, testing and merge phases become tasks in the pull request's own queue; what pm did as orchestration becomes negotiation inside the pull request artifact.

**What it enables.** A stuck pull request surfaces its own impasse. Instead of an external watcher inferring "this is stuck" from the outside, the pull request's own self-maintenance raises the impasse as a want — the artifact says it is stuck. The watcher's stuck-detection logic stops being external scaffolding and becomes the artifact's own concern.

**Prior-work cluster it draws on.** The actor model and contract-net (Section 1) — the phases become peer tasks negotiating the content of the change, not steps a scheduler sequences; the negotiation-protocol literature supplies the shape of that exchange.

### Instance 3 — pm's orchestration becomes the artifact protocol

**pm today.** pm is a state machine, and `project.yaml` holds the workflow state that machine runs on. That central state is a recurring source of friction: it is a single file many processes contend over, so concurrent work collides on it — merge conflicts on `project.yaml`, a merge already in progress when another wants to start, stale-state notifications when one process's view falls behind.

**Living-artifact version.** pm becomes a renderer and a host. Every flow it runs today — starting a pull request, reviewing, testing, merging, the watchers, synchronization — becomes a *task type* over the artifact substrate. `project.yaml` no longer holds workflow state at all.

**What it enables.** It removes the central state machine. This is where the plan's "no central arbiter" claim gets its most concrete grounding: pm's state machine *is* the central arbiter today — every flow routes through it — and Instance 3 is, precisely, the removal of that arbiter. The claim is not abstract; it names a specific component of pm and commits to deleting it.

**Prior-work cluster it draws on.** Linda tuple spaces (Section 1) — the artifact substrate, with no orchestrator above it, is structurally a shared content-addressed pool. The LLM-OS framing (Section 4) — pm reduced to a thin host around an intelligent substrate is the LLM-OS shape.

### Instance 4 — code as living artifacts (stretch study)

**pm today.** Nothing. pm does not touch program optimization at all; this instance is entirely new ground.

**Living-artifact version.** Functions and modules become living artifacts that negotiate optimizations peer-to-peer. The plan's worked scenario: code-artifact A notices, through its own profiling-driven self-maintenance, that it spends most of its time on a task X coming from artifact Y, and opens a negotiation directly with Y — proposing, for instance, that Y send X less often or pre-aggregated — with no central optimizer brokering the exchange.

**What it enables.** Autonomous program optimization with no central profiler-plus-optimizer. The system's pieces tune themselves in parallel; the human sits at the boundary, surfacing only where the artifacts could not resolve something, not on the critical path of every optimization.

**Prior-work cluster it draws on.** Market-based and decentralized coordination (Sections 1 and 5) — agents reaching agreement through local exchanges rather than central decree — and the self-organizing-systems literature (Section 5), where coordination is an emergent property of the units rather than an imposed structure.

### Where these instances lead

Instances 1–4 are what the plan commits to building. The plan also names four follow-on directions the same substrate would unlock once it exists: **new shapes of evolutionary algorithm** (a population of living candidates that negotiate their own selection, rather than passive genomes scored by an external fitness function — see Section 6); **self-organizing knowledge bases** (notes and references that maintain their own links and negotiate consolidation); **self-tuning infrastructure** (configuration and services that observe their own efficacy and converge without a human operator); and **living research workflows** (hypotheses and experiments that surface to the researcher only when consensus among them breaks down). These are not on the plan's critical path — they are substrate-enabled follow-ons, each a domain where the same data structure removes a bottleneck currently handled by external orchestration. The plan's job is to build the substrate well enough that any of them becomes a low-friction next step.

---

## Conclusion: an old vision, newly buildable

The plan's contribution is best stated in one sentence, and the whole survey above is the case for it: **the plan builds a work-coordination-and-agency layer over artifacts — a data structure that holds unsettled state as first-class, that is relational, and that relies on intelligence to resolve conflicts — and the closest prior art, the Mesh Memory Protocol, is a candidate memory layer beneath it, not a competitor.** That is the claim. It is, deliberately, "something people have gestured at before, newly enabled by LLMs." This conclusion makes that case in four steps.

### (a) The vision is old — and the plan should say so plainly

Nothing in the *aspiration* is unprecedented, and the survey above names the ancestors honestly:

- **Engelbart's NLS (1962, 1968)** imagined the document as a live, shared, manipulable surface between human and machine — not an inert file, but a medium that responds.
- **Blackboard systems (Hearsay-II, 1980)** imagined a shared workspace that multiple intelligences read, write, and coordinate through, rather than passing messages directly.
- **The actor model (1973)** imagined computation as autonomous units with their own state, coordinating without a central clock or scheduler.
- **Linda tuple spaces (1985)** imagined coordination through a shared, content-addressed pool that processes post into and draw from, naming no one.

Each of these holds a piece of "living artifacts." Decentralized units, a shared active workspace, coordination without an arbiter, the document as a first-class participant — the plan's vision is assembled from parts that have been in the literature for decades. The plan's posture — "inspiration, not blueprint" — is exactly right, and it should claim the lineage proudly rather than apologize for it.

### (b) Why the prior visions stalled — the determinism constraint

These visions did not become the general substrate the plan describes, and the reason is specific and shared. In every one of them, the "intelligence" inside a unit had to be **deterministic and programmed in advance**. An actor's behavior is a fixed program. A blackboard knowledge source is a hand-written specialist. A Linda process matches tuples by a fixed rule. A CRDT merges by a fixed mathematical law. When two edits conflict, or an artifact's state stops cohering, *something* has to decide what to do — and in all the prior work that something was either a deterministic rule or a central arbiter running one. There was no third option. You could not put open-ended judgment *inside* the structure, because open-ended judgment did not exist as a component you could instantiate cheaply and ubiquitously. CodeCRDT measures the cost of that constraint precisely: a CRDT gives you guaranteed syntactic convergence, and still leaves 5–10% of conflicts *semantically* unresolved — the residue that needs judgment, not a merge rule.

### (c) What LLMs change — intelligent conflict resolution as a primitive

This is the enabler, and it is genuinely new. A large language model makes *intelligent conflict resolution* a primitive — a component cheap and general enough to instantiate inside a data structure, the way a sort function or a hash table is a component. The conflict between two edits, or between an artifact and itself, or between an artifact and a neighbor, can now be resolved by reasoning over the integrity constraint rather than by a deterministic merge rule or a manager-intelligence above the system. The third option that did not exist for Engelbart, for the blackboard designers, for Gelernter — *put the judgment in the unit* — exists now. That is why the plan's framing of prior systems holds: they were "boxed in by determinism and programmability constraints," and that box is exactly what LLMs remove.

### (d) The plan's contribution — building that data structure on a real substrate

The contribution is not the vision and not the enabler. It is **specifying and building the data structure the enabler now permits, and proving it on a real substrate.** Concretely, that data structure is:

- **Unsettled state as first-class.** Unlike a markdown file or a database row, the artifact's state is not a single committed value. The structure represents unsettled state as first-class: proposals in flight, not just committed content — in-flight, not-yet-resolved tasks converging through negotiation. The structure has to represent the unresolved, not just the resolved. (The plan's own contribution statement uses the word "non-deterministic" for this property; it is imprecise — "non-deterministic" properly means outcomes not determined by inputs — and the plan owner may want to replace it with this description of unsettled-state-as-first-class.)
- **Relational.** The artifact carries its relations, not only its content: negotiation history, cross-artifact references, the want-dependencies between an artifact and the tasks acting on it and the artifacts around it. Artifacts negotiate with each other; the structure makes those relations legible.
- **Intelligence-resolved.** Conflicts are resolved by LLM reasoning over the artifact-integrity constraint — no deterministic merge rule, no central adjudicator. This is the part that was impossible before, and the part the prior visions could only gesture at.

And the plan proves it on a real substrate, in sequence — the four instances Section 9 lays out. The contribution is proven by *building* it: Instance 1 (pm's plan files), Instance 2 (pm's pull-request specifications), and Instance 3 (pm's own orchestration state, which removes pm's central state machine) carry the data structure into a working project-management tool, not a research demo. Instance 4 — the code stretch study — is the demonstration that the substrate generalizes beyond project management to code itself: functions and modules negotiating their own optimization show the same data structure is not specific to plans and pull requests. Section 8's grounding is the same point in the deployed tool's own vocabulary: Claude Code has a static-config tier and a reactive-session tier and nothing between them; the living-artifacts data structure is the missing middle — a first-class, continuously co-authored, between-sessions artifact.

### The closest prior art — the Mesh Memory Protocol — is a layer beneath, not a competitor

The single closest work to the plan is the **Mesh Memory Protocol** (MMP, arXiv:2604.19540, 2026), and the relationship is worth stating with care, because it is *layered* — not competing, and not identical.

MMP solves cross-session agent-to-agent knowledge sharing. Its four primitives are CAT7 (a fixed seven-field typed schema for a "Cognitive Memory Block"), SVAF (per-field, role-indexed acceptance — a receiver decides field by field what to take from a peer), inter-agent lineage (every claim traceable to its source), and remix (a receiver stores its own role-evaluated understanding of what it accepted). MMP is "specified, shipped, and running in production across three reference deployments" — which the references note honestly: running, but in the authors' own reference implementations, not verified commercial third-party adoption. It is the strongest deployment claim among the recent works, and the closest prior art on the *mechanics* the plan's substrate needs.

But MMP's *subject* and the plan's *subject* differ, and they differ along three axes the plan should walk explicitly:

- **Self-organization of work.** MMP has none. MMP is a mesh of agent peers sharing memory; the only "organization" in it is the topology of who-shares-with-whom. MMP does not decide what work happens, in what order, or by whom — its "mesh" is a *sharing topology*, not a work-coordination mechanism. "No central arbiter" is trivially true of MMP because nothing is being scheduled or adjudicated at all. The plan's subject is exactly the opposite: self-organization *of work* — tasks negotiating which proposals run in parallel, preempt, or merge, with selection and ordering emerging from negotiation.
- **Task scheduling and lifecycle.** MMP has no task concept — no queue, no lifecycle, no scheduling. In the plan, the **task is the atom**: tasks have a lifecycle (entry → specialization → in-flight → landed/folded/dropped) where each phase is a property of the *live task's trajectory* through negotiation, not a queue position. This is the plan's core machinery and MMP has no analog of it.
- **The unit of the data structure — the "living document" mismatch.** MMP's unit, the Cognitive Memory Block, is *what one agent tells another* — a knowledge-and-message unit, produced by one agent and selectively absorbed by others; it flows *between* agents. The plan's unit, the artifact, is *what agents work on, and which also works on itself* — a plan file, a PR spec, eventually pm itself, carrying a task queue, a negotiation history, a self-maintenance schedule, and "wants." It is the durable object the whole project is organised around, made capable of maintaining itself; it is the thing the work happens *to*, not a thing that flows between workers. These are different kinds of object — "living document," in the plan's sense of a document with agency over its own coherence, is not what a CMB is.

Two further differences follow from those axes. On **agency**: MMP's memory is passive — CMBs do not generate tasks, have no wants, do not negotiate; the plan's artifact spawns its own self-maintenance tasks from its own wants. On **integrity**: MMP's SVAF is *per-receiver* admission control, a receiver-side filter — there is no shared object whose integrity all participants are accountable to; the plan's integrity is a property *of the artifact* that every negotiating task is accountable to, a shared constraint that shapes which negotiated outcomes are admissible.

The honest framing is therefore a layered one. MMP solves a real problem the plan also has: the plan's open questions include *what is the artifact's persistent representation, how does the live state of in-flight tasks persist across pm restarts, what does a task see when prompted to respond to another task's proposal* — and MMP's CAT7 typed schema, per-field semantic evaluation, and lineage are a credible substrate for that persistence-and-sharing layer. The plan could adopt MMP-like primitives there rather than reinvent them. That is "building on," and it is fine. But the plan's subject — task negotiation, emergent work scheduling, the artifact's self-maintenance, integrity as a shared constraint, agency relocated into the artifact — is a layer **above** MMP, one MMP does not address. MMP is a memory protocol; the plan is a work-coordination-and-self-maintenance substrate.

Stated as the plan's contribution: *the Mesh Memory Protocol solves cross-session agent-to-agent knowledge sharing — a typed memory block (CAT7), per-field role-indexed acceptance (SVAF), and lineage. The living-artifacts plan shares one layer with MMP and could build on it: the artifact's open questions about persistent representation and cross-restart in-flight state are the problem MMP's primitives address, and the plan should adopt MMP-like typed-schema-plus-lineage primitives there rather than reinvent them. But MMP's subject and the plan's subject differ. MMP coordinates knowledge between agents; it has no task concept, no scheduling, no self-organization of work — its "mesh" is a sharing topology, not a work-coordination mechanism. The plan's subject is exactly what MMP omits: tasks as the atom, a task lifecycle whose phases are trajectories rather than queue positions, work scheduling that emerges from peer negotiation rather than from a scheduler, artifacts that spawn their own self-maintenance from their own "wants," and integrity as a constraint the whole negotiation is accountable to rather than a per-receiver acceptance filter. And the units differ in kind: MMP's Cognitive Memory Block is what one agent tells another; the plan's artifact is the durable object the project is organised around, made capable of maintaining itself. The plan builds the work-coordination-and-agency layer; MMP, or a protocol like it, is a candidate memory layer beneath it. The contribution is the upper layer — and "living document," in the plan's sense of a document with agency over its own coherence, is not what a CMB is.*

### The other close prior art corroborates the direction

The remaining works nearest the plan are academic demonstrations on narrower slices. **CodeCRDT** does CRDT-plus-LLM coordination for code-merge specifically, and its 5–10% semantic-conflict measurement is the empirical motivation for the plan's intelligence-resolved layer — a separate group independently sizing the exact gap the plan fills. **SwarmSys** is a decentralized coordination architecture studied in isolation; it shows the coordination layer works, and stops there. **"Drop the Hierarchy"** is a controlled study, not a system; it supplies direct evidence that capable LLM agents self-organize productively, and its strong-model-privilege finding is the basis of the cost-stratification bet discussed in Section 5. **MAIF** names the artifact-centric framing the plan uses, but fuses verification into the data layer where the plan fuses agency. **TheBotCompany** and the commercial **Swarms** framework are central-coordinator designs — foils for the plan, not prior art that preempts it. Together these works corroborate the plan's direction: independent groups, on narrower problems, are finding that decentralized LLM coordination works. What none of them builds is the work-coordination-and-agency layer over a general artifact, inside a working tool. That layer is the plan's job.

### Read on the framing

The plan's research direction survives this survey; three of its sub-claims need narrowing in the plan's own text, and the survey supplies the narrowed wording rather than certifying the loose wording. The plan's four boldest moves — that prior coordination systems were boxed in by determinism, that there is no central arbiter, that living units open a different mode of evolutionary computation, that the "wants" scaffold is operational and not decorative — hold *as directions*, with these calibrations:

- The determinism diagnosis is the strong half of the prior-systems claim; the "central scheduler" half is false for three of the four systems and the plan should narrow that sentence (Section 1).
- "No central arbiter" should be stated in the plan's text as "no central *adjudicator*" — a claim about who decides outcomes, compatible with structural priors like fixed ordering, which "Drop the Hierarchy" finds outperform pure structurelessness (Sections 4 and 5).
- The evolutionary-computation direction does not "hold" as a headline; Section 6 shows it is mostly inherited from Promptbreeder, FunSearch, AlphaEvolve and ADAS. It narrows to a single untested sliver — *negotiated internal selection* — which the plan should carry openly as a narrow long-term direction, not a contribution.
- The "wants" scaffold is grounded in the persona-prompting literature, with a cheap confirmatory experiment named (Section 7).

The contribution, stated precisely, is the headline narrowed: a data structure for artifacts that holds unsettled state as first-class, is relational, and is intelligence-resolved — a work-coordination-and-agency layer over artifacts, with MMP-like typed memory as a candidate substrate beneath it. It is an old vision that LLMs make buildable, proven on pm itself. Keeping the direction does not mean certifying every loose sub-claim; the three narrowings above are part of keeping the direction honestly.

### Coverage gaps in this review

- **The specific framing "anthropomorphize a non-agent artifact as having wants"** has no direct empirical study that this review could locate; Section 7's verdict rests on analogy to person-persona prompting.
- **Negotiated, internal selection for evolutionary computation** (Section 6) is unclaimed *and* untested — this review can say no one has done it, but not whether it works.
- **Some classic sources** (Agha's 1986 actor semantics, Nii's 1986 blackboard survey, the Dias 2006 market-coordination survey) were characterized from abstracts and secondary summaries rather than full-text reads; the characterizations are standard but not verified line-by-line.
- **"Drop the Hierarchy and Roles" (arXiv:2603.28990)** is very recent (2026) and, at the time of writing, a preprint not yet peer-reviewed; its 25,000-run result is load-bearing in Sections 5 and the conclusion and should be re-checked against the published version if one appears.

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
- The companion review `pm/docs/literature-review-user-model.md` is cited for the persona/role-prompting evidence in Section 7; its own references (Salewski 2023, Deshpande 2023, Gupta 2023, the Persona Selection Model) carry that section's empirical weight.
