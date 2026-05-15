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

This review surveys the literature each of those claims sits in. It is organized into eight sections matching the plan's own topic clusters, then a conclusion that states — point by point — where the plan inherits from prior work, where it diverges, and where its contribution is genuinely new. A companion review, `literature-review-user-model.md`, covers persona and role-prompting in depth; Section 7 cross-references it rather than repeating it.

### What surrounds the plan

The short version, previewed here so the reader can calibrate: almost every *primitive* the plan needs already exists in a mature form. Decentralized coordination without a scheduler is fifty years old (actor model, 1973). Negotiation-by-bidding is forty-five years old (contract-net, 1980). Indirect coordination through a shared workspace is the blackboard model and Linda tuple spaces. Merging concurrent edits without a central referee is a solved problem (operational transformation, 1989; conflict-free replicated data types, 2011). The "document that is also a program" is literate programming (1984) and computational notebooks. And — most pointedly — the last twelve months have produced LLM-agent systems that are *strikingly* close to the plan's architecture: decentralized multi-agent coordination over a shared state (CodeCRDT, 2025), AI agents as peers in a conflict-free replicated document (Yjs-based agent work, 2026), and a large empirical study that directly tests "self-organizing agents vs. designed hierarchies" (the "Drop the Hierarchy" paper, 2026).

The plan's honest framing — "we study the prior work for inspiration and vocabulary, not as a blueprint" — turns out to be exactly the right posture. What is *new* in the plan is narrower than its headline, but it is real, and the conclusion states it precisely.

---

## 1. Concurrency and coordination models without a central scheduler

The plan's claim that prior coordination systems "assumed a central scheduler or arbiter" deserves a careful, honest answer, because it is *partly* true and *partly* not. This section walks the four systems the plan names.

### The actor model (Hewitt, Bishop & Steiger, 1973; Agha, 1986)

The **actor model** is a way of structuring computation in which the only kind of object is an *actor* — an independent unit that has its own private state and communicates only by sending *messages* to other actors. There is no shared memory and no global clock; an actor reacts to a message by doing some local work, sending more messages, and possibly creating new actors. (The everyday analogy: a large office where every worker has their own desk and locked drawers, and the only way to get anything done is to send memos.)

Carl Hewitt, Peter Bishop and Richard Steiger introduced it in 1973 ("A Universal Modular ACTOR Formalism for Artificial Intelligence") and Gul Agha gave it a rigorous semantics in his 1986 book. The model is explicitly **decentralized**: there is no central scheduler. Each actor processes its own messages in its own order.

So is the plan's claim — "they assumed a central scheduler" — wrong about actors? *Mostly, yes.* The actor model never assumed one. What the plan is *right* about is the other half of its claim: actors were "boxed in by determinism and programmability constraints." An actor's behavior is a fixed program. When an actor receives a message it cannot interpret, nothing creative happens — it follows its code. The "intelligence" of an actor is whatever a programmer wrote into it ahead of time. The plan's move is to replace that fixed program with an LLM, so the unit can interpret an unforeseen message and *reason* about a response. That is a genuine difference, and the plan should make it precisely: not "actors had a central scheduler" (they didn't) but "actors' per-unit behavior was a static program; ours is a general reasoner."

### Contract-net protocol (Smith, 1980)

The **contract-net protocol** is a negotiation mechanism for distributed problem-solving, published by Reid G. Smith in 1980 (*IEEE Transactions on Computers*). It works like subcontracting in business. A node with a task to delegate broadcasts an *announcement*; other nodes reply with *bids* describing how well they could do it; the announcer picks a winner and *awards* the contract. Task allocation happens through this announce–bid–award cycle, with no master scheduler deciding who does what.

This is the closest classical ancestor of the plan's "tasks negotiate peer-to-peer." Smith explicitly framed it as a "negotiation metaphor." Again the plan's "central arbiter" claim is too strong: contract-net is decentralized by design. But contract-net negotiates over *who runs a fixed task* — the task's content is settled; only its assignment is up for bid. The plan's tasks negotiate over the *content of the proposal itself*. The plan's own §"Tasks as the atom" makes exactly this point ("they treated the task's output as fixed and negotiated over scheduling. Here the task's content itself is the negotiation surface"), and it is correct. That is the real divergence from contract-net, and it is sharper than "they had a scheduler."

### Blackboard systems (Hearsay-II; Erman, Hayes-Roth, Lesser & Reddy, 1980; Nii, 1986)

A **blackboard system** is an AI architecture organized around a shared workspace — the "blackboard" — that multiple specialist modules (called *knowledge sources*) read from and write to. No knowledge source talks to another directly; they coordinate *through* the shared blackboard, each one watching for a state it can contribute to. The canonical example is Hearsay-II, the 1971–76 speech-understanding system (Erman, Hayes-Roth, Lesser & Reddy, *ACM Computing Surveys*, 1980). H. Penny Nii's two-part 1986 survey in *AI Magazine* is the standard reference.

Here the plan's "central arbiter" claim lands more squarely. Classic blackboard systems *did* have a central component: the **control component** (or "scheduler") that, on each cycle, looked at the whole blackboard and decided which knowledge source got to run next. Hearsay-II's control was a focus-of-attention mechanism. So blackboards are a real example of "assumed a central scheduler." The plan's relationship to blackboards is the most direct of the four: the plan's *artifact* is a blackboard (a shared workspace multiple tasks read and write), but the plan **deletes the control component** and replaces it with peer-to-peer negotiation plus the "integrity" constraint. That is a meaningful, statable inheritance-and-divergence: *the plan is a blackboard without a scheduler.*

### Linda tuple spaces (Gelernter, 1985; Carriero & Gelernter, 1989, 1992)

**Linda** is a coordination language by David Gelernter and Nicholas Carriero (Yale, mid-1980s). Its core idea is the **tuple space**: a shared, content-addressable pool of data records ("tuples"). Processes coordinate by *posting* tuples into the pool (`out`), *reading* them (`rd`), and *atomically removing* them (`in`). A process never names another process; it just drops data into the pool, and whoever wants it picks it up by matching on content. The 1985 paper is "Generative Communication in Linda"; the 1992 *CACM* paper "Coordination Languages and Their Significance" argued that coordination is a language-design concern as fundamental as control flow.

Linda is genuinely decentralized — there is no scheduler — and it directly informs the plan's open question about the artifact's persistent representation. A 2025 industry essay, "Our AI Orchestration Frameworks Are Reinventing Linda" (Carvalho), argues that modern LLM-agent task systems — git-backed task files, SQLite task stores, shared-filesystem coordination with polling — are *rediscovering* tuple spaces without knowing it. The plan should read this as a caution: its "live task queue" inside an artifact is, structurally, a tuple space scoped to one document. That is not a flaw — it is a well-understood, robust pattern — but the plan should name it as such rather than present the task queue as novel.

### Honest verdict on the plan's framing

The plan's sentence "most of them assumed a central scheduler or arbiter" is **imprecise and should be corrected**. Of the four, only blackboard systems clearly had a central control component. Actors, contract-net, and Linda are all decentralized. The *accurate* version of the plan's claim is the one it already makes elsewhere and should promote: these systems made the per-unit intelligence **small, fixed, and pre-programmed**, and they negotiated over **scheduling or assignment, not over the content of the work**. Replacing the fixed per-unit program with a general reasoner, and moving the negotiation surface onto the work's content, is the genuine shift. "Determinism and programmability constraints" is the right diagnosis; "central scheduler" is not.

---

## 2. Concurrent shared state: CRDTs and operational transformation

The plan's open questions ask, directly: "What is the artifact's persistent representation? ... CRDT-friendly for concurrent in-flight task state?" and "How does the live state of in-flight tasks persist?" This is the most technically settled area the plan touches.

### Operational transformation (Ellis & Gibbs, 1989)

**Operational transformation** (OT) is the original technique for letting multiple people edit one document at once without a central lock. Clarence Ellis and Simon Gibbs introduced it in their 1989 paper "Concurrency Control in Groupware Systems," built into the GROVE group outline editor. The idea: when two users make edits at the same time, each user's edit is *transformed* against the other's so that both arrive at the same final document. (Concretely: if you insert a word at position 5 while I delete a word at position 2, my client adjusts your insert to position 4 before applying it.) OT became the engine behind Google Docs' real-time collaboration. Its two guarantees — *causality preservation* and *convergence* — are exactly the guarantees the plan needs for "multiple in-flight tasks act on overlapping regions of the artifact simultaneously."

### Conflict-free replicated data types (Shapiro, Preguiça, Baquero & Zawirski, 2011)

A **conflict-free replicated data type** (CRDT) is a data structure designed so that independent copies, edited concurrently and offline, are *mathematically guaranteed* to converge to the same value once they exchange updates — with no central coordinator and no merge conflicts. Marc Shapiro, Nuno Preguiça, Carlos Baquero and Marek Zawirski formalized CRDTs in 2011 (SSS 2011, "Conflict-Free Replicated Data Types"), defining the state-based and operation-based variants and the conditions a type must satisfy. CRDTs are the modern, decentralized answer to the same problem OT solved with a central server.

This directly answers one of the plan's open questions. If the plan wants in-flight task state that multiple tasks edit concurrently and that survives a restart, the off-the-shelf answer is "model the artifact, or its task queue, as a CRDT." The plan does not need to invent this; it needs to *adopt* it.

### Recent work: CRDTs for LLM agents (2025–2026)

Three very recent pieces of work bring this lineage right up against the plan:

- **CodeCRDT (arXiv:2510.18893, 2025)** — "Observation-Driven Coordination for Multi-Agent LLM Code Generation." Multiple LLM agents generate code concurrently into a CRDT-backed shared state. Crucially, the coordination is **decentralized and observation-driven**: "agents coordinate by monitoring a shared state with observable updates and deterministic convergence, rather than through explicit message passing." This is *very close* to the plan's no-central-arbiter model, and it is close to a blackboard too. Its honest finding across 600 trials is sobering: parallel coordination produced up to a 21% speedup on some tasks but up to a **39% slowdown on others**, with semantic (meaning-level, not syntactic) conflicts in 5–10% of cases despite perfect CRDT convergence. The lesson for the plan: a CRDT guarantees the *text* merges cleanly; it does *not* guarantee the *meaning* is coherent. The plan's "artifact integrity" constraint is precisely the gap CRDTs leave open — and CodeCRDT shows that gap is real and costly.
- **"AI agents as CRDT peers" (Electric, 2026)** — an industry write-up of treating an LLM agent as just another peer in a Yjs (a popular CRDT library) collaborative document, appearing to humans with a cursor like any other collaborator. This is the plan's "humans and tasks are participants in the same negotiation" — already shipping as a pattern.
- **"Collaborative Document Editing with Multiple Users and AI Agents" (arXiv:2509.11826, 2025)** — describes itself as "the first to investigate how multiple people work together with multiple shared AI agents within a shared document environment," with agent profiles and tasks as shared objects in the document. This is structurally the plan's "artifact contains its task queue."

The takeaway for Section 2: the plan's concurrency substrate is not a research risk. OT and CRDTs are mature; the agent-on-CRDT pattern is being actively built. The plan's contribution is *not* the merge mechanism — it is the **semantic** layer (integrity) sitting on top of a merge mechanism that already works.

---

## 3. The living-document and augmentation vision

The plan's artifact is "a structured object ... text-renderable, that humans can audit." That sentence sits downstream of a sixty-year lineage.

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

Andrej Karpathy's widely-circulated framing casts the LLM as the *kernel* of a new kind of operating system: the model is the processor, the context window is RAM, tools and retrieval are peripherals. It is a framing, not a system, but it is the vocabulary the plan's "pm becomes a renderer and a host for the artifacts, not a state machine" is reaching for. The plan's eventual milestone ("pm's orchestration is the artifact protocol") is an LLM-OS-shaped claim: the *substrate* is intelligent, and the tool around it is thin.

### AutoGen, MetaGPT, ChatDev — and the honest confrontation

The plan claims "no central arbiter, peer-to-peer negotiation." This is a **strong claim against the dominant design** of current multi-agent LLM systems, and the plan should confront it head-on:

- **AutoGen** (Wu et al., 2023, arXiv:2308.08155) is Microsoft's multi-agent conversation framework. Its "group chat" mode — which sounds the most peer-to-peer — in fact runs through a **group chat manager**: a component that "broadcasts messages and decides who the next speaker will be." That is a central arbiter. AutoGen's peer-to-peer appearance is mediated by a scheduler.
- **MetaGPT** (Hong et al., 2023, arXiv:2308.00352) encodes fixed **Standard Operating Procedures** — Product Manager → Architect → Engineer — into the agent pipeline. The roles and their order are pre-designed by humans.
- **ChatDev** (Qian et al., ACL 2024) runs a fixed 7-role pipeline (CEO → CPO → CTO → Programmer → Reviewer → Tester → Designer).

So the plan is correct that the *mainstream* of multi-agent LLM work is orchestrator-centric or fixed-pipeline. Its "no central arbiter" claim is a genuine departure **from AutoGen/MetaGPT/ChatDev**. But — and this is the load-bearing honesty — it is *not* a departure from the research frontier of the last twelve months, which has already moved exactly where the plan is going. See Section 5.

---

## 5. Self-organizing and emergent coordination

This section contains the prior art that most closely preempts the plan's core claims. The plan owner should read it carefully.

### Stigmergy and swarm intelligence

**Stigmergy** is indirect coordination: agents change a shared environment, and other agents respond to those changes, with no direct messaging — the textbook example is ants laying pheromone trails. In software, stigmergy "looks like writing to a shared memory store, updating a task queue, or flagging states in a vector database." The plan's artifact-with-a-task-queue, where tasks see "what other proposals are in flight nearby," is a **stigmergic** design: tasks coordinate by reading and writing the shared artifact, not by addressing each other. The plan should adopt this word — it is the precise term for what it is doing.

### Market-based coordination

Smith's contract-net (Section 1) spawned a large lineage of **market-based coordination**: agents bid, in a simulated economy, for tasks. Dias, Zlot, Kalra & Stentz's survey "Market-Based Multirobot Coordination" (*Proceedings of the IEEE*, 2006) is the standard reference. It is relevant because the plan's "integrity as a shared constraint that emerges from negotiation, not enforcement" is in this family — distributed agreement reached through local exchanges rather than central decree. The plan's twist is that the "currency" is not price but *integrity pressure*, and the bidders are LLM reasoners rather than cost functions.

### Recent work: self-organizing LLM agents — the closest preemption

Two 2025–2026 papers sit almost on top of the plan:

- **SwarmSys (arXiv:2510.10047, 2025)** is "a closed-loop framework that enables LLM agents to coordinate through lightweight, pheromone-like traces ... fostering self-organized collaboration ... *without centralized control*." That is the plan's headline architecture, already published and named.
- **"Drop the Hierarchy and Roles: How Self-Organizing LLM Agents Outperform Designed Structures" (arXiv:2603.28990, 2026)** is the single most important paper for this plan. It runs **25,000+ task runs** across 8 models, 4–256 agents, 8 coordination protocols, and 4 complexity levels, directly comparing centralized coordination, fully-autonomous self-organization, and hybrids. Its findings bear directly on the plan's bets:
  - Groups of LLM agents given a mission, a communication protocol, and a capable model — **but no pre-assigned roles** — spontaneously invent organizational structure (5,006 unique roles emerged from 8 agents) and exhibit *voluntary self-abstention* (an agent withdraws from a task outside its competence). This strongly supports the plan's "wants"/self-organization premise.
  - But **neither maximum control nor maximum autonomy wins.** A *hybrid* — fixed agent ordering, autonomous role selection — beat fully-autonomous coordination by 44% and centralized coordination by 14%. Pure peer-to-peer self-organization was *not* the best performer.
  - And, critically: self-organization "is a privilege of strong models. Below a capability threshold ... autonomy reverses and hurts performance for weaker models."

The implications for the plan are direct and double-edged. The plan's "general intelligence in every unit removes the ceiling" claim is **empirically supported** — *for capable models*. But the plan's cost-stratification idea (§"Privileged participants") — "demote routine specializations to cheaper intelligence" — runs straight into this paper's threshold finding: below a capability threshold, autonomy *hurts*. The plan's safety net (privileged participants catching cheap-task drift) is a reasonable hypothesis, but "Drop the Hierarchy" is direct evidence that cheap units in a self-organizing system are a real risk, not a free optimization. The plan should cite this paper and treat its cost-tier section as an open empirical question, not a settled design.

Equally, "Drop the Hierarchy" partly *contradicts* the plan's strict "no central arbiter." Its best-performing protocol kept *one* centralized element (fixed ordering). The plan's pure peer-to-peer stance is not the configuration the largest existing study found best. The plan should engage this honestly: "no central arbiter" may need to soften to "minimal central structure," with the empirical question — how minimal — flagged as something the early PRs must test.

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

So two of the plan's three pillars are already gone in the literature: the genome is no longer a passive string (Promptbreeder, ADAS use code/text manipulated by LLMs), and selection without an external objective exists (novelty search). **What remains genuinely unclaimed** is the plan's third element: *selection emerging from peer-to-peer negotiation among the candidates themselves*, where a candidate evaluates its own fitness in context and negotiates with neighbors. In every system above, an *external* loop still drives selection — FunSearch's evaluator, AlphaEvolve's automated evaluators, ADAS's meta-agent, Promptbreeder's fitness on a training set. None of them lets the *candidates negotiate their own survival*.

**Honest verdict.** The plan's "qualitatively different" framing **overstates the gap** if read as "no one has living, intelligent genomes" — they do. It is **defensible, narrowly**, if restated as: *prior LLM-evolutionary work retains an external selection loop; the plan proposes selection internal to the population, via the same negotiation dynamics that drive its other artifacts.* That is a real, unclaimed position — but it is a narrow one, and "qualitatively different mode" should be rewritten to claim exactly that and no more. It is also, candidly, the least-evidenced part of the plan (it is explicitly a stretch direction), and whether negotiated selection produces useful evolutionary pressure is entirely untested.

---

## 7. Anthropomorphization as an operational prompt technique

The plan states its "wants" are "a prompt scaffold, not a metaphor": prompting an LLM to reason *as if* an artifact had wants is meant to measurably shape its output. The companion review `literature-review-user-model.md` covers persona and role-prompting in depth (its §2, "Persona, role, and framing effects on performance," and its treatment of the Persona Selection Model); this section cross-references it and addresses only the question specific to this plan: *does prompting an LLM to reason "as if X had wants" change its output, and has anyone tested it?*

The relevant evidence, from the companion review and from the persona-prompting literature it surveys:

- **Persona prompting demonstrably changes output.** Salewski et al.'s "In-Context Impersonation" (NeurIPS 2023) shows that prefixing a prompt with an expert persona reliably changes task performance; an expert persona beats a non-expert one across domains. So "telling the model to reason as a particular kind of entity" is an established, measurable lever — this supports the plan's premise that the "wants" scaffold is operational, not decorative.
- **But the effect is double-edged and unstable.** Deshpande et al. ("Toxicity in ChatGPT," EMNLP 2023 Findings) found persona assignment can multiply toxicity sixfold; Gupta et al. ("Bias Runs Deep," 2023) found personas surface stereotypical reasoning even on neutral tasks; and the persona-prompting literature documents performance drops of *up to 30 percentage points* from *irrelevant* persona details. The plan's "wants" scaffold is a persona-shaped intervention and inherits this instability: framing an artifact as wanting things will change the LLM's reasoning in ways that are not all benign and not fully predictable.
- **The specific framing "as if this artifact had wants" is not directly tested.** The persona literature tests personas that are *people* (an expert, a child, a demographic group). The plan's move — anthropomorphizing a *non-agent* (a document) as having desires — is a specific variant with, as far as this review found, **no direct empirical study**. This is a genuine coverage gap. The closest analogue is "object personas" in design and social simulation, but nothing in the surveyed literature measures whether "reason as if this plan file wanted its PRs coherent" changes an LLM's output relative to a non-anthropomorphic instruction ("check that the PRs are coherent with the plan's motivation").

**Verdict for the plan.** The plan's claim that the "wants" framing is operational is *plausible* by analogy to persona prompting, but it is *unverified* for the specific case of anthropomorphizing an artifact. The plan's want-inference PR should include the obvious controlled comparison: run the same artifact through (a) a "wants"-framed prompt and (b) a plain instruction-framed prompt asking for the same self-maintenance tasks, and check whether the framing measurably changes the tasks produced. The plan currently asserts the framing has "teeth"; the literature says *test that.*

---

## 8. Grounding: the living-artifacts model versus Claude Code's current feature set

This section is load-bearing. The plan owner specifically asked for it: a sober, feature-by-feature comparison against the most widely-used tool in this space, so the plan reads as grounded analysis rather than a flashy demo. The source is the Claude Code large-codebase best-practices blog post (claude.com), and a companion analysis — the Cycle 6 regression addendum — which worked out the same abstraction gap for a different plan and reached a conclusion this plan should adopt.

A few terms first: **Claude Code** is Anthropic's command-line coding tool; pm is built on top of it (every task the plan runs ultimately spawns a Claude Code session). **CLAUDE.md** is a project-context file Claude Code reads at the start of every session. The other features are glossed inline below.

The companion addendum's core finding, which this section confirms and extends: **Claude Code's feature set assumes a static-config + reactive-session split.** Configuration (CLAUDE.md, skills, plugins) is human-authored and reviewed every "three to six months." Sessions are reactive — a human prompts, Claude acts, the session ends. There is **no abstraction in Claude Code for an artifact that is continuously co-authored and lives between sessions as first-class state.** The living-artifacts plan *is* that missing abstraction, made the explicit subject. Feature by feature:

**CLAUDE.md (context files Claude reads automatically).** *Relation to the plan:* CLAUDE.md is the closest existing thing to "an artifact that carries guidance for the intelligence." *The hack:* if you tried to build a living artifact out of CLAUDE.md, you would point a machine-append process at it — and immediately corrupt its contract. CLAUDE.md is *human-curated context humans expect to read and trust*; a file that the system continuously rewrites is no longer that. CLAUDE.md is also one undifferentiated blob — it cannot express "this part is the task queue, this part is negotiation history." *What the plan provides that CLAUDE.md can't:* a structured artifact with a typed task queue, negotiation history, and a self-maintenance schedule, with a clean separation between the human-auditable rendering and the machine-authored state.

**Hooks (scripts that run at fixed moments in a session).** *Relation:* hooks are how Claude Code "captures session learnings." *The hack:* a hook fires *once*, within *one* session; to make a living artifact you would need hooks to carry state forward across sessions, and the only place Claude Code auto-loads is CLAUDE.md — so you are back to the CLAUDE.md hack. *What the plan provides:* an artifact whose state *is* the cross-session substrate; the artifact lives between sessions by construction, not by a hook smuggling state into a config file.

**Skills (packaged, on-demand instructions for task types).** *Relation:* the plan's "operation classes" that a task picks up during specialization are skill-shaped — packaged vocabulary for a kind of work. *The hack:* skills are *human-authored and installed*; a living artifact whose self-maintenance tasks generate new operation classes has no home in Skills, because Skills carry no provenance ("which run authored this") and assume a human owns the file. The plan's *automated want-inference* PR — where the system synthesizes its own self-maintenance behavior — has no Skills analogue at all. *What the plan provides:* operation classes that the artifact's own intelligence can generate and negotiate, with provenance, rather than a static human-authored library.

**Plugins (bundles of skills + hooks + MCP config, installed as a unit).** *Relation:* a plugin is a static install. *The hack:* you could package "the artifact protocol" as a plugin, but a plugin is *configuration at rest*; the living-artifacts substrate is *a running system with evolving state* (in-flight tasks, negotiation histories). A plugin cannot *be* the running system. *What the plan provides:* the ongoing process and its state, which a plugin packages around but cannot contain.

**Subagents (isolated Claude instances with their own context, spawned to do a sub-task and return a result).** *Relation:* this is the closest Claude Code feature to the plan's "tasks." *The hack:* subagents are *within-task and hierarchical* — a parent spawns a child, the child returns, the parent decides. That is exactly the central-arbiter shape the plan rejects. To get peer-to-peer negotiation out of subagents you would have to build a coordination layer the subagent abstraction does not provide, and route all their communication through a parent — reintroducing the arbiter. *What the plan provides:* tasks that are peers, that negotiate with each other directly (stigmergically, through the shared artifact), and that persist between sessions rather than living and dying inside one parent's call.

**MCP servers (connections to external tools and data).** *Relation:* light. The plan could expose an artifact through MCP so other tools reach it. *Honest gap:* the plan does not engage MCP deeply, and should say so rather than imply it does. MCP is plumbing the plan *could* use, not a feature it competes with.

**Agentic search (Claude navigating the filesystem with grep/reads instead of a pre-built index).** *Relation:* pure substrate. Every task the plan runs will use agentic search to read the artifact and its surroundings. *What the plan adds here: nothing* — and the plan should say so plainly. Not every Claude Code feature is a contribution surface; agentic search is one the plan simply consumes.

**Plan mode (Claude proposes a plan and waits for human approval before acting).** *Relation:* plan mode is the *reactive, human-gated* version of what the plan wants to make *continuous and mostly un-gated*. In plan mode, the plan is a transient artifact inside one session, and the human approves it once. *The hack:* you could imagine re-entering plan mode repeatedly to simulate a living plan, but each entry is a fresh, stateless proposal — there is no carried-forward negotiation history, no in-flight tasks, no self-maintenance. *What the plan provides:* the plan-as-artifact *persists*, accretes negotiation history, and runs its own self-maintenance between human touches — the human is a boundary the plan occasionally crosses, not a gate every proposal stops at.

**The agent-manager role.** The blog post names an emerging "agent manager" — a hybrid PM/engineer who curates configuration, owns the plugin marketplace and CLAUDE.md conventions. This is the closest the blog comes to the plan's thesis, and the contrast is exact: the agent manager is *a human who curates static config on a 3–6-month cadence*. The plan's privileged-participant model replaces that with *a human who participates in negotiations where they happen to show up* — the curation is continuous and mostly automated (self-maintenance tasks, want-inference), and the human's role shrinks to the boundary cases. The plan is, precisely, "the agent-manager role, made continuous and largely automated."

**Honest scoping, both directions.** The blog post names real Claude Code limitations — codebases with hundreds of thousands of folders, non-git version control. The plan **inherits** these; it does not address them. And the plan does not *replace* any Claude Code feature — it builds a layer *on top of* the reactive session and *beside* the static config, occupying the gap between them. The plan's contribution, stated in the blog's own vocabulary: **Claude Code has a static-config tier and a reactive-session tier and nothing in between; the living-artifacts plan is the missing middle tier — a first-class, continuously co-authored, between-sessions artifact.** That is concrete, it is grounded in the current tool, and it is not a demo.

---

## Conclusion: where the plan inherits, diverges, and is genuinely new

Following the methodology's principle — *narrow the contribution; don't collapse it* — here is the precise accounting.

### Where the plan inherits (and should say so)

- **Decentralized coordination without a scheduler** is the actor model (1973), and the plan's per-unit autonomy is an actor-shaped idea.
- **Negotiation as a coordination primitive** is contract-net (1980); the announce–bid–award shape is a direct ancestor of task negotiation.
- **A shared workspace multiple intelligences read and write** is the blackboard model (Hearsay-II, 1980) and Linda tuple spaces (1985). The plan's artifact-with-a-task-queue *is* a tuple space scoped to one document, and its coordination is **stigmergic** — it should adopt that word.
- **Concurrent edits converging without a referee** is operational transformation (1989) and CRDTs (2011). The plan does not need to invent this; it should adopt a CRDT for in-flight task state.
- **The document that is also a machine-actionable structure** is literate programming (1984) and computational notebooks.
- **Selection without an external objective** is novelty search (2011); **LLM-driven evolution of non-passive genomes** is Promptbreeder, FunSearch, AlphaEvolve, ADAS (2023–2026).
- **Persona framing measurably shaping LLM output** is the persona-prompting literature (Salewski 2023 and the companion review's §2).

### Where the plan's framing needs correction

- **"They assumed a central scheduler or arbiter"** is imprecise: only blackboards did. Actors, contract-net, and Linda were decentralized. The accurate claim — which the plan already makes elsewhere — is that prior systems' per-unit intelligence was *small, fixed, and pre-programmed*, and they negotiated over *scheduling/assignment, not the content of the work*.
- **"No central arbiter"** is a real departure from AutoGen/MetaGPT/ChatDev — but *not* from the 2025–2026 frontier (SwarmSys, CodeCRDT, "Drop the Hierarchy"), which has already moved there. And "Drop the Hierarchy" found that *pure* peer-to-peer was not optimal — a minimal central element (fixed ordering) won. The plan should soften to "minimal central structure" and treat "how minimal" as an early-PR empirical question.
- **"A qualitatively different mode" of evolutionary computation** overstates the gap: living, intelligent genomes already exist. The defensible, narrow version: *prior LLM-evolutionary work keeps an external selection loop; the plan proposes selection internal to the population via negotiation.* That is unclaimed — but narrow, and untested.
- **The "wants" scaffold has "teeth"** is plausible by analogy but unverified for the specific case of anthropomorphizing a non-agent artifact. The plan should run the controlled comparison rather than assert it.

### Where the plan is genuinely new

After the narrowing, the residual contribution is real and worth stating precisely. No prior work this review found combines **all** of the following:

1. **The negotiation surface is the *content* of the work, not its scheduling or assignment.** Contract-net negotiates assignment; blackboards schedule knowledge sources; CRDTs merge text. The plan's tasks negotiate the *substance* of an evolving proposal. This is the plan's sharpest, best-defended novel claim.
2. **"Artifact integrity" as a semantic constraint tasks are accountable to, layered on top of a syntactic merge mechanism.** CodeCRDT shows precisely the gap the plan fills: CRDTs guarantee the text merges; they do *not* guarantee the meaning is coherent (5–10% semantic conflicts). The plan's integrity layer is a named, deliberate answer to a gap the closest prior art empirically demonstrates exists.
3. **The artifact's self-maintenance generated by anthropomorphic want-inference, and the want-inference itself eventually automated.** Self-organizing agents invent roles (SwarmSys, "Drop the Hierarchy"), but the plan's specific mechanism — *ask, of each artifact, what it would want if it were alive, and turn the answer into negotiating tasks* — is, as a stated method, not in the surveyed literature.
4. **The integration into a real project-management tool as the missing middle tier** between Claude Code's static config and reactive sessions (Section 8). The plan is not a research demo; it is the named abstraction for a gap a widely-used tool actually has.

### Honest read on the plan's "general intelligence removes the ceiling" framing

Does the framing survive contact with the literature? **Partially, and with one important correction.**

It *survives* in this sense: the strongest relevant evidence — "Drop the Hierarchy and Roles" (25,000+ runs) — directly confirms that *capable* LLM agents, given a mission and a protocol but no imposed structure, self-organize productively and beat human-designed hierarchies. The plan's bet that general intelligence in every unit enables coordination that fixed-program units could not is *empirically supported for strong models*.

It *does not survive unmodified* on two points. First, "removes the ceiling" is too absolute: the same study found self-organization is "a privilege of strong models," and below a capability threshold autonomy *hurts* — which puts the plan's cost-stratification idea (cheap intelligence for routine tasks, privileged participants as the safety net) in direct tension with the best available evidence. That section should be reframed as an open empirical question. Second, "qualitatively different" and "no central arbiter" are both stronger than the literature supports — the frontier already has decentralized LLM coordination, and the best-performing configuration kept a sliver of central structure.

The honest summary: the plan's *direction* is well-supported and, in fact, where the research frontier is actively heading — which is a point in its favor, not against it. Its *novelty* is narrower than the headline ("everything alive, ceiling removed") and sharper than the headline once narrowed: the negotiation-over-content surface, the integrity-as-semantic-constraint layer, anthropomorphic want-inference as a self-maintenance mechanism, and the grounding as Claude Code's missing middle tier. The plan's own posture — "inspiration, not blueprint" — is the correct one; it should keep it, correct the four overstatements above, and let the narrowed contribution stand, because narrowed it is genuinely defensible.

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

- Anonymous / "Drop the Hierarchy and Roles" authors. 2026. "Drop the Hierarchy and Roles: How Self-Organizing LLM Agents Outperform Designed Structures." arXiv:2603.28990.
- "CodeCRDT" authors. 2025. "CodeCRDT: Observation-Driven Coordination for Multi-Agent LLM Code Generation." arXiv:2510.18893.
- "Collaborative Document Editing with Multiple Users and AI Agents." 2025. arXiv:2509.11826.
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
