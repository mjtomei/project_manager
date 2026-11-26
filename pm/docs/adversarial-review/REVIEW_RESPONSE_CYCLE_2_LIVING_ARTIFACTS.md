# Review Response — Cycle 2 (living-artifacts literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_2_LIVING_ARTIFACTS.md`

Cycle 2 surfaced 6 substantive findings (three of them prior-art misses from the citation-graph walk) and 17 phrasing/accessibility/structure findings. Per the methodology's procedural rule and this loop's standing protocol — *don't trust the reviewer* — the parent agent fetched and read the abstract of every one of the five arXiv IDs the review flagged before drafting a word of this response. The verification caught reviewer overstatement on the highest-severity finding, which is the pattern that has held in every cycle of this loop. The standing calibration applies: keep the plan's framing unless prior art saw genuine commercial/real-world success; the core contribution is the data structure (relational, intelligence-resolved-conflicts, carries unsettled in-flight state as first-class); narrow precisely, don't collapse.

**Headline result of verification:** the blackboard-revival finding (SUBSTANTIVE-1) is **partially overstated**. The two papers do revive the blackboard architecture for LLM agents, and one has the 13-57% numbers — but neither *deletes the central controller* the way the review claims, and both treat the blackboard as **passive shared state**, not as a living artifact with agency. The finding survives as a real prior-art addition, but at corrected (narrower) scope: it preempts the *vocabulary* "LLM blackboard," not the plan's thesis (the artifact has agency, carries unsettled in-flight proposals as first-class state, self-maintains).

---

## Part 1 — The five arXiv IDs, verified against their abstracts

### SUBSTANTIVE-1 — The "blackboard revival" (arXiv:2507.01701, arXiv:2510.01285)

#### arXiv:2507.01701 — "Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture"

**Verbatim abstract** (Bochen Han, Songmao Zhang; submitted 2 July 2025):

> "In this paper, we propose to incorporate the blackboard architecture into LLM multi-agent systems (MASs) so that (1) agents with various roles can share all the information and others' messages during the whole problem-solving process, (2) agents that will take actions are selected based on the current content of the blackboard, and (3) the selection and execution round is repeated until a consensus is reached on the blackboard. We develop the first implementation of this proposal and conduct experiments on commonsense knowledge, reasoning and mathematical datasets. The results show that our system can be competitive with the SOTA static and dynamic MASs by achieving the best average performance, and at the same time manage to spend less tokens. Our proposal has the potential to enable complex and dynamic problem-solving where well-defined structures or workflows are unavailable."

**What it actually does.** It is the first LLM implementation of the classical blackboard architecture: agents share all messages on a blackboard; on each round, agents "are selected based on the current content of the blackboard"; rounds repeat until consensus. Evaluated on commonsense/reasoning/math datasets; competitive with SOTA multi-agent systems at lower token cost.

**Where the reviewer overstated.** The review quotes the paper's framing — "subordinate agents independently decide whether they possess the capability, knowledge, or interest to contribute" — and concludes "the control component is gone and self-selection replaces it." The *abstract* does not say that. Clause (2) — "agents that will take actions **are selected** based on the current content of the blackboard" — is passive-voice and does not state *what* does the selecting. It is consistent with a selection step that is itself a control component (the classical blackboard's scheduler reads the board and picks the next knowledge source — that is exactly clause 2). The abstract gives no basis for "the central controller is deleted." The reviewer read the no-controller claim into the paper.

**Crucially — passive board or living artifact?** Passive. The board is shared state agents read and write. It does not carry wants, does not spawn its own tasks, does not self-maintain. The blackboard is the medium; the agents are the intelligence — the classical split.

#### arXiv:2510.01285 — "LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science"

**Verbatim abstract** (Salemi, Parmar, Goyal, Song, Yoon, Zamani, Pfister, Palangi; submitted 30 Sep 2025, revised 31 Jan 2026):

> "Advances in large language models (LLMs) have created new opportunities in data science, but their deployment is often limited by the challenge of finding relevant data in large data lakes. Existing methods struggle with this: both single- and multi-agent systems are quickly overwhelmed by large, heterogeneous files, and master-slave multi-agent systems rely on a rigid central controller that requires precise knowledge of each sub-agent's capabilities, which is not possible in large-scale settings where the main agent lacks full observability over sub-agents' knowledge and competencies. We propose a novel multi-agent paradigm inspired by the blackboard architecture for traditional AI models. In our framework, a central agent posts requests to a shared blackboard, and autonomous subordinate agents - either responsible for a partition of the data lake or retrieval from the web - volunteer to respond based on their capabilities. This design improves scalability and flexibility by removing the need for a central coordinator to know each agent's expertise or internal knowledge. We evaluate the approach on three benchmarks that require data discovery: KramaBench and modified versions of DSBench and DA-Code. Results show that the blackboard architecture substantially outperforms strong baselines, achieving 13%-57% relative improvements in end-to-end success and up to a 9% relative gain in data discovery F1 over the best baseline."

**What it actually does.** A data-discovery system over data lakes. It is blackboard-shaped: subordinate agents volunteer to respond to requests rather than being dispatched by capability-aware routing. The 13-57% number is real (relative improvement in end-to-end success on KramaBench / modified DSBench / DA-Code). The 9% F1 number is also real.

**Where the reviewer overstated — the load-bearing correction.** The review says the paper "shifts decision-making from a single coordinator to a distributed model" and reads it as deleting the central controller. The abstract says something materially narrower and explicitly **retains a central agent**: *"a central agent posts requests to a shared blackboard."* What the paper removes is the *requirement that the central coordinator know each agent's capabilities* — "removing the need for a central coordinator to know each agent's expertise or internal knowledge." That is decentralization of *capability knowledge*, not deletion of the central node. There is still a central agent that posts the requests and owns the request flow. This is **not** "blackboard without a controller." It is "blackboard with a controller that no longer needs a capability registry."

**Crucially — passive board or living artifact?** Passive. The board holds requests and responses; the central agent posts, subordinate agents volunteer. The board has no wants, spawns nothing, does not self-maintain.

#### What the plan does that neither paper does

1. **The board itself has agency.** In both papers the blackboard is passive shared state; the agents act, the board does not. The plan's artifact spawns its own self-maintenance tasks from its own "wants."
2. **In-flight unsettled state as first-class.** Both papers post findings/requests/responses and iterate to consensus. Neither models competing in-flight proposals held in superposition with their own negotiation history as first-class structure.
3. **The unit is a durable project artifact** (plan, PR, pm itself), not an ephemeral problem-solving board torn down when the task completes.
4. **No central node at all (in Instance 3's terminus).** Neither paper deletes the central node; 2510.01285 explicitly keeps a central request-posting agent.

#### Does the blackboard revival preempt the plan's thesis, or only the vocabulary?

**Only the vocabulary, plus a narrow slice.** The honest read: there is a live 2025-2026 research program reviving the blackboard architecture for LLM agents, and the plan can no longer use "blackboard" as a forty-year-old vocabulary word — it is a current, competitive term. That much of the finding is real and the review is right to flag it as a miss. But the review's specific framing — that this program does "the specific move the review credits the plan with" and makes "blackboard without a scheduler" read as *preempted* — does not survive verification. Neither paper deletes the controller; 2510.01285 explicitly keeps a central agent; both keep the blackboard passive. The plan's thesis (the artifact is itself an agent; it carries unsettled in-flight state as first-class; the unit is the durable artifact) is untouched by either paper.

**Decision: ACCEPT WITH CORRECTED SCOPE.** Add both papers. Correct the reviewer's scope: they revive the blackboard *vocabulary and shared-workspace pattern* for LLM agents, with measured gains, and they decentralize *capability knowledge*; they do **not** delete the central controller and they do **not** give the board agency. The plan should cite the lineage proudly (it strengthens "people are converging on this") and state the residual precisely.

**Replacement statement for §1 and conclusion §(a)** (corrected from the reviewer's proposed wording, which overstates):

> "The blackboard architecture is not just forty-year-old history — it is being actively revived for LLM multi-agent systems (Han & Zhang, arXiv:2507.01701, 2025; Salemi et al., arXiv:2510.01285, 2025, which reports 13-57% relative gains on data-discovery tasks). These systems inherit the classical blackboard's shared workspace and let agents self-select what to contribute. They differ from the plan in two ways the plan should state plainly: the board in both remains *passive* shared state — the agents act, the board does not — and neither deletes the central node (Salemi et al. explicitly retains a central agent that posts requests; it decentralizes only the capability knowledge a coordinator would otherwise need). The plan inherits the blackboard pattern from this live lineage, and adds what the lineage does not have: a blackboard that is itself an agent — carrying its own wants, spawning its own maintenance tasks — and that holds competing in-flight proposals as first-class state, not just posted findings."

---

### SUBSTANTIVE-2 — "From Soliloquy to Agora" (arXiv:2604.25847)

**Verbatim abstract** (Jianghao Lin, Zi Ling, Chenyu Zhou, Tianyi Xu, Ruoqing Jiang, Zizhuo Wang, Dongdong Ge; submitted 28 April 2026):

> "Optimization modeling underpins real-world decision-making in logistics, manufacturing, energy, and public services, but reliably solving such problems from natural-language requirements remains challenging for current large language models (LLMs). In this paper, we propose Agora-Opt, a modular agentic framework for optimization modeling that combines decentralized debate with a read-write memory bank. Agora-Opt allows multiple agent teams to independently produce end-to-end solutions and reconcile them through an outcome-grounded debate protocol, while memory stores solver-verified artifacts and past disagreement resolutions to support training-free improvement over time."

**What it actually does.** Agora-Opt is an agentic framework scoped to *optimization modeling* (turning natural-language requirements into solvable optimization problems). Multiple agent teams each produce an end-to-end solution independently; the solutions are reconciled through an "outcome-grounded debate protocol" — debate scored against verifiable solver outcomes. A read-write memory bank stores solver-verified artifacts and past disagreement resolutions.

**Is it artifact-centric or agent-centric?** Agent-centric. The *agent teams* produce, debate, and reconcile. The memory bank stores artifacts but is passive storage — the artifacts do not negotiate; the agents do. This is decentralized reconciliation *between agents* over candidate solutions, not artifacts negotiating with each other.

**What the plan does that Agora-Opt does not.** Agora-Opt reconciles concurrent candidate *solutions to one problem* via outcome-grounded (solver-verified) debate — it has a ground-truth oracle (the solver) to ground the debate. The plan's domain has no solver oracle: integrity is a soft, judgment-evaluated constraint, not a solver result. Agora-Opt has no self-maintaining artifact, no wants, no task lifecycle, no general artifact substrate; it is scoped to one problem class.

**Decision: ACCEPT WITH CORRECTED SCOPE.** The review's framing ("decentralized intelligence-based reconciliation of concurrent candidate artifacts") is slightly loose — it reconciles candidate *solutions*, agent-produced, grounded in a solver oracle. But the core point holds: decentralized, intelligence-based, no central selector reconciliation of concurrent candidates *exists and is published*. So conclusion §(c)'s "genuinely new" cannot stand (see Finding 4). Cite Agora-Opt in §5 as a recent neighbor: it does outcome-grounded decentralized reconciliation for optimization modeling; the plan generalizes the pattern to a self-maintaining general artifact substrate with no solver oracle to ground the debate. Narrowing, not collapse — the residual (general artifact, wants, lifecycle, no oracle) survives.

---

### SUBSTANTIVE-3 — InfiAgent and "Everything is Context" (arXiv:2601.03204, arXiv:2512.05470)

#### arXiv:2601.03204 — "InfiAgent: An Infinite-Horizon Framework for General-Purpose Autonomous Agents"

**Verbatim abstract** (Chenglin Yu, Yuchen Wang, Songmiao Wang, Hongxia Yang, Ming Li; submitted 6 January 2026):

> "LLM agents can reason and use tools, but they often break down on long-horizon tasks due to unbounded context growth and accumulated errors. Common remedies such as context compression or retrieval-augmented prompting introduce trade-offs between information fidelity and reasoning stability. We present InfiAgent, a general-purpose framework that keeps the agent's reasoning context strictly bounded regardless of task duration by externalizing persistent state into a file-centric state abstraction. At each step, the agent reconstructs context from a workspace state snapshot plus a fixed window of recent actions."

**What it actually does.** InfiAgent solves the *context-window* problem for a long-horizon *single agent*. It externalizes persistent state to files so the agent's reasoning context stays bounded regardless of task length; each step the agent rebuilds context from a workspace snapshot plus recent actions. The motivation is context-growth and error accumulation, not multi-agent authoritative state.

**Where the reviewer overstated.** The review's quote — "treating the file system as the authoritative and persistent record of the agent's actions, environment, and intermediate artifacts" — is a *paraphrase*; the abstract says "externalizing persistent state into a file-centric state abstraction" for the purpose of *bounding context*. It is single-agent context management, not "the artifact, not a state machine, holds the workflow state" in the plan's multi-party, negotiated sense. The file is passive externalized memory for one agent. There is no agency in the file, no negotiation, no multi-party authority.

#### arXiv:2512.05470 — "Everything is Context: Agentic File System Abstraction for Context Engineering"

**Verbatim abstract** (Xiwei Xu, Robert Mao, Quan Bai, Xuewu Gu, Yechao Li, Liming Zhu; submitted 5 December 2025):

> "Generative AI (GenAI) has reshaped software system design by introducing foundation models as pre-trained subsystems that redefine architectures and operations. The emerging challenge is no longer model fine-tuning but context engineering-how systems capture, structure, and govern external knowledge, memory, tools, and human input to enable trustworthy reasoning. Existing practices such as prompt engineering, retrieval-augmented generation (RAG), and tool integration remain fragmented, producing transient artefacts that limit traceability and accountability. This paper proposes a file-system abstraction for context engineering, inspired by the Unix notion that 'everything is a file'. The abstraction offers a persistent, governed infrastructure for managing heterogeneous context artefacts through uniform mounting, metadata, and access control. Implemented within the open-source AIGNE framework, the architecture realises a verifiable context-engineering pipeline, comprising the Context Constructor, Loader, and Evaluator, that assembles, delivers, and validates context under token constraints. As GenAI becomes an active collaborator in decision support, humans play a central role as curators, verifiers, and co-reasoners. The proposed architecture establishes a reusable foundation for accountable and human-centred AI co-work, demonstrated through two exemplars: an agent with memory and an MCP-based GitHub assistant. The implementation within the AIGNE framework demonstrates how the architecture can be operationalised in developer and industrial settings, supporting verifiable, maintainable, and industry-ready GenAI systems."

**What it actually does.** A file-system abstraction for *context engineering* — a persistent, governed infrastructure for managing context artefacts (knowledge, memory, tools, human input) with uniform mounting, metadata, and access control. It is about traceability, accountability, and verifiable context assembly under token limits. Humans are "curators, verifiers, and co-reasoners." It is infrastructure for governing context, in the lineage of MAIF's auditability concern more than the plan's agency concern.

**What the plan does that neither does.** Both are externalized-state / file-as-substrate work. Neither gives the file/artifact agency: InfiAgent's file is bounded memory for one agent; "Everything is Context"'s file system is governed, human-curated context infrastructure. Neither has wants, self-maintenance, peer negotiation between artifacts, or a task lifecycle. "Everything is Context" is explicitly human-curated; the plan's artifact self-maintains.

**Decision: ACCEPT WITH CORRECTED SCOPE.** The review's framing — "file/artifact-as-authoritative-state, closest neighbor to Instance 3" — is half right. They are externalized-state work and the plan should cite them; §8's implication that a between-sessions first-class artifact is the plan's unclaimed space cannot stand unqualified. But "closest neighbor to pm-as-artifact-protocol" overstates: InfiAgent is single-agent context-bounding, "Everything is Context" is governed context infrastructure with humans curating. Neither approaches "pm's orchestration becomes the artifact protocol" (a negotiated, multi-party, self-organizing substrate). Cite both as the externalized-state lineage; narrow §8/conclusion from "the missing abstraction" to: "Claude Code lacks a between-sessions first-class artifact; the research frontier (InfiAgent, 'Everything is Context') has converged on file-as-persistent-state — but as passive externalized memory or human-curated context infrastructure. The plan's addition is *agency* in that artifact, not the externalization itself."

---

## Part 2 — Findings 4, 5, 6

### Finding 4 — Conclusion §(c) "genuinely new" overclaims

**Agree.** Given Agora-Opt (verified: decentralized intelligence-based reconciliation, published) and the blackboard-revival lineage (verified: live LLM-blackboard program), the unhedged absolute "This is the enabler, and it is genuinely new" does not survive a 2026 walk. Putting LLM judgment in the resolution step is no longer unprecedented. Note the verification *narrows* the reviewer's case slightly: the blackboard papers do not put intelligence "in the resolution mechanism inside a self-maintaining artifact" — they keep passive boards — so the strongest preemption evidence for §(c) is Agora-Opt and CodeCRDT's own follow-on motivation, not the blackboard papers. The conclusion holds: cut "genuinely new."

**Proposed replacement for §(c)** (keeps the framing's direction, drops the absolute):

> "What LLMs change is that intelligent conflict resolution becomes cheap enough to instantiate *inside a data structure* — the way a sort function or hash table is a component. This is no longer unprecedented: multiple 2025-2026 systems put LLM judgment in a reconciliation step on narrower problems — Agora-Opt does outcome-grounded decentralized reconciliation for optimization modeling; CodeCRDT's own measured 5-10% semantic residue motivates exactly this layer. What the plan adds is to make intelligence the resolution layer of a *general, self-maintaining artifact substrate* — not a narrow problem class, and with no solver oracle to ground the judgment. The third option that did not exist for Engelbart, the blackboard designers, or Gelernter — *put the judgment in the unit* — exists now, and the plan's move is to make it the resolution layer of a general artifact rather than a single problem domain."

### Finding 5 — Cost-stratification cites only the bearish half of "Drop the Hierarchy"

**Agree.** §5's "bet with hedge" rewrite is honest about the threshold finding (autonomy reverses below a capability threshold) but omits the same paper's bullish number: open-source models at **95% of closed-source quality for 24x lower cost**. Citing only the bearish half of a paper you lean on is a selective read. The fix makes the bet's evidence two-sided.

**Spec the edit (§5, the cost-stratification "bet" paragraph).** After the sentence stating the bet, add:

> "'Drop the Hierarchy' supplies direct evidence *for* the bet as well as the threshold finding against it: the same study found open-source models reaching 95% of closed-source quality at 24x lower cost — the routine tier is already near-frontier on that study's tasks. The open risk is precise: whether 'near-capable on benchmark tasks' transfers to 'capable enough to negotiate without degrading artifact integrity' — which the study does not test. So the bet rests on a measured cost-capability gap that is already small; the residual uncertainty is the benchmark-to-negotiation transfer, not whether cheap models are broadly capable."

### Finding 6 — "No central adjudicator" vs. the integrity-maintenance task as a relocated adjudicator — NEEDS PLAN-OWNER INPUT

**This finding is flagged for the plan owner and is deliberately NOT resolved in this response.**

The tension, stated precisely. The plan claims "no central adjudicator" — conflicts resolve through peer negotiation against the artifact-integrity constraint, with no manager-intelligence above the negotiation. But the plan also specifies an *integrity-maintenance task*: the task that catches a bad proposal, that the artifact spawns from its "wants" to keep itself coherent. "Drop the Hierarchy" found fully-autonomous coordination underperformed a structured hybrid by 44% — some adjudication-like structure beats none. If the integrity-maintenance task is the thing that catches a degraded proposal, then functionally it *plays an adjudication role* — it evaluates proposals against a standard and can reject them. Calling it "not an adjudicator" because it is a task rather than a manager-intelligence may be a distinction of *form* (where the adjudicating code sits) without a difference of *function* (something still adjudicates). The plan may have relocated adjudication into the artifact and the maintenance task rather than eliminated it.

This is a genuine conceptual tension, not a wording nit. Two honest options — the plan owner should pick:

- **Option (a) — concede and reframe.** Concede the integrity-maintenance task plays an adjudication-like role, and reframe the claim as: "no adjudicator *above* the negotiation — the integrity-maintenance task is a high-weight *participant in* the negotiation, not an observer above it. It can be argued with, outvoted by sufficient peer weight, and is itself subject to the same integrity constraint; it does not sit outside the negotiation issuing verdicts." This keeps the claim true at the level of *structure* (no node with unilateral, unaccountable veto) while honestly admitting an adjudication *function* is distributed into a weighted participant. It aligns with the privileged-participant model already in the plan — the integrity-maintenance task is simply another privileged participant.
- **Option (b) — something else.** E.g., distinguish *adjudication* (deciding a winner) from *integrity-checking* (flagging incoherence without deciding the resolution), and argue the maintenance task only does the latter — it raises a want, it does not pick the outcome; the picking is still peer negotiation. Or accept the relocated-adjudicator framing outright and drop "no central adjudicator" in favor of "the adjudication is decomposed across the artifact's own maintenance tasks rather than concentrated in a manager." Whether (b) is more defensible than (a) depends on what the plan actually specifies the integrity-maintenance task to *do* — decide outcomes, or only flag — which is a plan-design question the response cycle cannot settle.

**Recommended response-cycle action:** mark §5 (and the conclusion's "Read on the framing" bullet) with a TODO that the "no central adjudicator" claim must be reconciled with the integrity-maintenance task, pending the plan owner's choice between (a) and (b). Do not edit the claim until the plan owner picks. Option (a) is the response author's *guess* at the better option because it aligns with the existing privileged-participant gradient — but this is explicitly the plan owner's call.

---

## Part 3 — Structure, accessibility, and prose findings (roll-up)

These 17 findings are accepted for the edit pass as a batch; the edit agent should apply each against the review's specific cited text. Summary of agreement:

**Block 2 — structure (STRUCT-1..4): agree, apply.**
- STRUCT-1: cut conclusion §(a) and §(b) by half — they re-narrate §§1-3.
- STRUCT-2: compress §8 (Claude Code grounding) to ~3 paragraphs; move the feature-by-feature walk to an appendix.
- STRUCT-3: cut the conclusion §(d) instance re-walk to one sentence; keep §9.
- STRUCT-4: cut §7's verdict paragraph to three clauses.

**Block 3 — accessibility (ACCESS-1..8): agree, load-bearing, apply each with the review's proposed gloss.**
- ACCESS-1: stop using bare "convergence" after first gloss; say "all copies end up identical."
- ACCESS-2: add the standalone syntactic/semantic gloss sentence early in §2.
- ACCESS-3: gloss "superposition" on first quote ("many possible versions held at once, none yet final").
- ACCESS-4: re-anchor or de-acronym OT, EA, CMB, SVAF, CAT7 — replace with plain phrases after first use.
- ACCESS-5: gloss "Yjs" as "a ready-made software component that implements CRDTs"; gloss Strassen's algorithm and the cap-set problem, or cut.
- ACCESS-6: rewrite the §2, §4, §6 section openings to name a concrete reader benefit (use the review's proposed openings).
- ACCESS-7: lead the OT example with the outcome, not the position arithmetic.
- ACCESS-8: gloss "first-class" on first use ("stored and handled as seriously as the finished version, not bolted on").

**Block 4 — prose (PROSE-1..6): agree, low severity, apply.**
- PROSE-1: cut emphasis density — one italic per paragraph; structural bold only.
- PROSE-2: consolidate per-section "the plan should" imperatives into one sentence per section.
- PROSE-3: split the §5 CodeCRDT long sentence (use the review's rewrite).
- PROSE-4: rewrite the §1 "holds up / one does not" self-contradicting sentence.
- PROSE-5: cut "worth stating / worth being precise about" announcements; keep the content.
- PROSE-6: cut the conclusion's MMP restatement — keep the italic block, trim the three paragraphs above it to a two-sentence lead-in.

---

## Edits checklist

1. **Add the blackboard-revival papers** (arXiv:2507.01701, arXiv:2510.01285) to §1 and References, at *corrected* scope: they revive the blackboard pattern and vocabulary for LLM agents with measured gains (13-57%), they decentralize *capability knowledge*, but they do **not** delete the central controller (2510.01285 keeps a central request-posting agent) and the board stays **passive**. Use the corrected replacement statement in Part 1.
2. **Update §1 and conclusion §(a)**: "blackboard" is a live 2026 term, not forty-year-old history; the plan inherits the pattern from a current lineage and adds board agency + first-class in-flight state.
3. **Add Agora-Opt** (arXiv:2604.25847) to §5 and References: decentralized outcome-grounded reconciliation of candidate solutions for optimization modeling; the plan generalizes the pattern to a self-maintaining general artifact with no solver oracle.
4. **Add InfiAgent** (arXiv:2601.03204) **and "Everything is Context"** (arXiv:2512.05470) to §8/§9 and References: the externalized-state lineage; correct scope — InfiAgent is single-agent context-bounding, "Everything is Context" is human-curated context infrastructure. Narrow §8's "missing abstraction" claim to "Claude Code lacks it; the frontier has converged on file-as-state but passive; the plan adds agency."
5. **Rewrite conclusion §(c)**: cut "genuinely new"; use the Finding 4 replacement statement.
6. **§5 cost-stratification**: add the 95%-quality-at-24x-cheaper number from "Drop the Hierarchy" (Finding 5 edit); state the residual as benchmark-to-negotiation transfer.
7. **Finding 6 — DO NOT EDIT THE CLAIM.** Mark §5 and the conclusion's framing bullet with a TODO: "no central adjudicator" must be reconciled with the integrity-maintenance task's adjudication-like role; **needs plan-owner input** — choice between Option (a) reframe-as-participant and Option (b).
8. Apply STRUCT-1..4, ACCESS-1..8, PROSE-1..6 against the review's cited text.

## Plan-owner items

- **Finding 6 (the relocated-adjudicator tension) — your call.** The integrity-maintenance task functionally adjudicates. Pick Option (a) — reframe "no central adjudicator" as "no adjudicator *above* the negotiation; the integrity-maintenance task is a high-weight *participant in* it" — or Option (b) (distinguish flagging from deciding, or concede and reframe as decomposed adjudication). The response author leans (a) for consistency with the privileged-participant gradient, but this is explicitly yours to decide.
- The blackboard-revival finding is real but the reviewer overstated it — the plan's thesis (artifact agency, first-class in-flight state) is *not* preempted, only the "blackboard" vocabulary's age. The plan should cite the revival as evidence the field is converging on the plan's neighborhood, not as a threat.

## Convergence note

Cycle 2's walk surfaced three real prior-art additions — all accepted, all at *narrower* scope than the reviewer proposed after abstract verification. The highest-severity finding (blackboard revival) was the most overstated: neither paper deletes the controller and both keep the board passive, so it preempts vocabulary, not thesis. This is the now-standard pattern of this loop — the reviewer is directionally right and consistently over-claims the magnitude. The plan's framing survives Cycle 2, narrowed in §(c) and §8, with Finding 6 the one genuinely unresolved item, deliberately left for the plan owner. Cycle 3 should pressure-test the §(c) rewrite and the Finding 6 resolution once the plan owner has chosen.

---

## Finding 6 — RESOLVED (plan-owner input, 2026-05-15)

The plan owner's guidance: "Ultimately we will do whatever works best, so it doesn't hinge on there being no adjudicator. But the idea is to build a system that can improve and maintain itself, in whole or part, without the intelligences (machine or human) that act as adjudicators now."

This dissolves the tension the reviewer flagged rather than choosing between options (a) and (b). The reviewer framed the integrity-maintenance task as a "relocated adjudicator" that contradicts a "no central arbiter" claim. But the plan's goal was never the dogmatic absence of adjudication. The goal is to **remove the system's dependency on the adjudicators it relies on *today*** — the human reviewer and pm's central state machine.

The integrity-maintenance task *is* adjudication-flavored — and that is the contribution, not a contradiction of it. The adjudication function gets **relocated from outside the system to inside it**: instead of a human or pm's state machine sitting above the work and deciding, the living substrate carries its own integrity-maintenance as first-class tasks. "Relocated adjudicator" is accurate and is exactly the design — adjudication absorbed into the self-maintaining substrate.

**Edit (replaces finding 6's two options):**

- Drop any framing of "no central arbiter" as an absolute. The lit review should not claim adjudication is eliminated.
- Reframe the claim as: the plan removes the system's dependence on *external, currently-relied-on* adjudicators (human review, pm's central state machine) by internalizing adjudication into the substrate's own integrity-maintenance tasks. The integrity-maintenance task is adjudication relocated from outside the system to inside it — part of the living substrate, not an external intelligence the system depends on.
- Use "in whole or part" honestly: the plan does not claim total elimination of human or external judgment. It claims the system can carry progressively more of its own maintenance and improvement. The human still enters — at the boundary, for the work the system's own adjudication could not resolve. This connects to and sharpens the plan's existing "human as boundary, not bottleneck" framing: the integrity-maintenance task is the *mechanism* by which the human stops being the bottleneck adjudicator.
- This is a whole-system goal, not a claim about the negotiation's internal topology. Whether, locally, an integrity task is "a participant in" vs. "above" a given negotiation is an implementation detail the plan can settle whichever way works best. The load-bearing claim is the dependency removal, not the topology.
