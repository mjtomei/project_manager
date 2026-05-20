# Citation Audit — Living-Artifacts Literature Review

**Artifact audited:** `pm/docs/literature-review-living-artifacts.md`.

**Scope.** Full-text reads (arXiv abstracts and where retrievable, paper bodies) of the load-bearing citations across the executive summary, the four plan-instance sections, the conclusion, and Appendix B §§1–7. Run as the dedicated citation-use audit per `CITATION_USE_AUDIT.md`, before the next adversarial-review cycle.

**Method.** WebFetch against arXiv abstract pages for the recent (2025–2026) citations and the classical paper landing pages where available. Where the abstract sufficed (which it usually did, because the load-bearing claims in the lit review are abstract-level claims like "decentralized" / "no central manager" / "X% gain"), the abstract was the source. Where the lit review made an internal-methodology claim (figure semantics, mechanism description, scope claim), the abstract is flagged as insufficient and a full-text follow-up is recommended in-place.

**Load-bearing prioritization.** The load-bearing set is large (≈25 substantive entries). The audit is thorough on the top ~20 by load-bearing weight (the entire "three closest published papers" set, the four-instance grounding, the eight-cluster Appendix B), and lighter on classical citations (actor model, contract-net, Linda, OT, CRDT, Engelbart) whose roles in the lit review are uncontroversial.

**How to walk this.** Read top-to-bottom; apply or reject each proposed change. Faithful entries (no change required) are marked "faithful." A summary table at the end ranks entries by action required.

---

## Load-bearing citation set

Organized by the role each plays in the lit review's argument.

**Executive-summary three (the lit review's own "three closest published papers"):**
1. AgentNet — [arXiv:2504.00587](https://arxiv.org/abs/2504.00587)
2. ScienceClaw + Infinite — [arXiv:2603.14312](https://arxiv.org/abs/2603.14312)
3. Mesh Memory Protocol (MMP) — [arXiv:2604.19540](https://arxiv.org/abs/2604.19540)

**Plan-instance / framing anchors:**
4. MAIF — [arXiv:2511.15097](https://arxiv.org/abs/2511.15097) (preempts the "artifact-centric" phrase)
5. CodeCRDT — [arXiv:2510.18893](https://arxiv.org/abs/2510.18893) (the 5–10% semantic-conflict figure)
6. "Drop the Hierarchy and Roles" — [arXiv:2603.28990](https://arxiv.org/abs/2603.28990) (25,000-task study; the four cited statistics)
7. SwarmSys — [arXiv:2510.10047](https://arxiv.org/abs/2510.10047)
8. Agora-Opt — [arXiv:2604.25847](https://arxiv.org/abs/2604.25847) (decentralized reconciliation precedent)
9. Semantic Consensus — [arXiv:2604.16339](https://arxiv.org/abs/2604.16339) ("Semantic Intent Divergence"; 41–86.7% failure rate)
10. Han & Zhang blackboard — [arXiv:2507.01701](https://arxiv.org/abs/2507.01701)
11. Salemi LLM-blackboard — [arXiv:2510.01285](https://arxiv.org/abs/2510.01285) (13–57% gains)
12. "Consensus Trap" — [arXiv:2604.17139](https://arxiv.org/abs/2604.17139)
13. Ψ-Arch — [arXiv:2604.13934](https://arxiv.org/abs/2604.13934)
14. LSS ("Loosely-Structured Software") — [arXiv:2603.15690](https://arxiv.org/abs/2603.15690)
15. MemoRepair — [arXiv:2605.07242](https://arxiv.org/abs/2605.07242)
16. CORAL — [arXiv:2604.01658](https://arxiv.org/abs/2604.01658)
17. A-Evolve — [arXiv:2602.00359](https://arxiv.org/abs/2602.00359)
18. "Last Human-Written Paper" — [arXiv:2604.24658](https://arxiv.org/abs/2604.24658)
19. "Intermediate Artifacts as First-Class Citizens" — [arXiv:2605.12087](https://arxiv.org/abs/2605.12087)
20. Externalization survey — [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)
21. InfiAgent — [arXiv:2601.03204](https://arxiv.org/abs/2601.03204)
22. "Everything is Context" — [arXiv:2512.05470](https://arxiv.org/abs/2512.05470)
23. CollabDoc — [arXiv:2509.11826](https://arxiv.org/abs/2509.11826)
24. TheBotCompany — [arXiv:2603.25928](https://arxiv.org/abs/2603.25928)
25. AgentsNet — [arXiv:2507.08616](https://arxiv.org/abs/2507.08616)

**Classical lineage (lighter check):**
- Hewitt 1973 / Agha 1986 (actor model); Smith 1980 (contract-net); Hearsay-II / Nii 1986 (blackboard); Gelernter 1985 (Linda); Ellis & Gibbs 1989 (OT); Shapiro 2011 (CRDT); Engelbart 1962/1968; Knuth 1984 (literate programming); Minsky 1986 (Society of Mind).

**Supporting (light):**
- MemGPT, AutoGen, MetaGPT, ChatDev, Promptbreeder, FunSearch, AlphaEvolve, ADAS, Karpathy LLM-OS, Carvalho "Reinventing Linda," Electric "AI Agents as CRDT Peers," Bret Victor / Dynamicland, Lehman & Stanley novelty search 2011. Persona-prompting citations (Salewski 2023, Deshpande 2023, Gupta 2023) carry their weight from the companion user-model review and its already-completed audit.

---

## I. The executive-summary three — closest published papers

These three are the lit review's own headline comparisons and carry the most argumentative weight.

### AgentNet — [arXiv:2504.00587](https://arxiv.org/abs/2504.00587)

**Doc passage as currently written** (verbatim, exec summary):
> **AgentNet (2025)** built a system where AI agents coordinate with no central manager. Verdict: it proves the no-manager idea works, but it coordinates *agents*, not self-maintaining *files*. Does not preempt the plan.

**Doc passage as currently written** (verbatim, B§5):
> **AgentNet (arXiv:2504.00587, 2025)** is the strongest *built* instance of orchestrator-free coordination: LLM agents specialize, evolve, and route tasks over a dynamically restructured DAG with no central manager, beating centralized baselines on accuracy. Its unit, though, is the *agent*: it has no shared data structure holding in-flight unsettled state, no task lifecycle, no wants. The plan's residual — the artifact itself as the coordinating substrate and a negotiating peer — is untouched by it.

**What the source actually says** (abstract):
> "fully decentralized coordination mechanism that eliminates the need for a central orchestrator"; agents operate within "a dynamically structured Directed Acyclic Graph (DAG)" that "adapts in real time to task demands"; agents "specialize, evolve, and collaborate autonomously"; route tasks "based on local expertise and context." The abstract does not describe a shared in-flight-state data structure, a task lifecycle, or "wants."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### ScienceClaw + Infinite — [arXiv:2603.14312](https://arxiv.org/abs/2603.14312)

**Doc passage as currently written** (verbatim, exec summary):
> **ScienceClaw + Infinite (2026)** built a layer that automatically cleans up when automated research tools produce contradictory or duplicated results. Verdict: among the closest published things to the plan's self-maintenance, but its files are passive records; the plan's files have their own goals. Does not preempt the plan.

**Doc passage as currently written** (verbatim, B§5):
> **ScienceClaw + Infinite (arXiv:2603.14312, 2026)** — independent agents conduct scientific investigation with no central coordination; an artifact layer records lineage as a DAG, and an "autonomous mutation layer" prunes that DAG to resolve conflicting or redundant workflows. […] The difference: ScienceClaw's artifacts are *immutable provenance records*; the pruning is a layer operating *over* the DAG, and the agency sits in the agents.

**What the source actually says** (abstract):
> "The ArtifactReactor enables plannerless coordination: peer agents discover and fulfill open needs through pressure-based scoring." Agents "produce immutable artifacts with typed metadata and parent lineage" preserving "full computational lineage as a directed acyclic graph (DAG)." "An autonomous mutation layer actively prunes the expanding artifact DAG to resolve conflicting or redundant workflows." Agency is **distributed**: agents "select and chain tools" and "broadcast unsatisfied information needs," but artifacts themselves become quasi-agents through the ArtifactReactor, which autonomously discovers needs and triggers "multi-parent synthesis across independent analyses."

**Verdict:** **over-characterizes the agency gap.** The lit review insists ScienceClaw's artifacts are passive provenance nodes and agency sits in the agents. The abstract is more hybrid than that: ArtifactReactor "autonomously discovers needs" and the autonomous mutation layer operates *on the artifact DAG* independently, which is closer to "artifacts driving work" than the lit review allows. The plan's residual narrows compared to the current framing — ScienceClaw is closer to the plan than the "passive records, no goals" line suggests.

**Substantive change proposed (rewrite for exec summary):**
> **ScienceClaw + Infinite (2026)** built a system in which independent agents conduct scientific investigation with no central coordination; an artifact reactor "autonomously discovers needs," and a separate autonomous mutation layer prunes the artifact DAG to resolve conflicts. Verdict: closer to the plan's self-maintenance than any other published system — agency in ScienceClaw is *distributed* across both agents and an artifact-reactor layer, not concentrated in agents. The residual narrows accordingly: the plan's distinctive contribution is the artifact *as a negotiating peer* (with explicit wants and a task lifecycle inside the artifact itself), not artifact-side autonomy per se, which ScienceClaw already exhibits in narrow form. Does not preempt the plan.

**Substantive change proposed (rewrite for B§5):**
> **ScienceClaw + Infinite (arXiv:2603.14312, 2026)** — peer agents discover and fulfill open needs through pressure-based scoring (the "ArtifactReactor"); an autonomous mutation layer prunes the artifact DAG to resolve conflicting or redundant workflows. Agency is distributed: the abstract describes the ArtifactReactor as "autonomously discovering needs," so the framing that artifacts are purely passive provenance nodes overstates the gap. The plan's residual is sharper-stated as: artifacts that hold their own explicit *wants* and a *task lifecycle* as first-class state, and that negotiate proposal content peer-to-peer with other artifacts, rather than triggering reactive multi-parent synthesis on satisfied needs. The gap to the plan is narrower than B§5 currently reads.

---

### Mesh Memory Protocol (MMP) — [arXiv:2604.19540](https://arxiv.org/abs/2604.19540)

**Doc passage as currently written** (verbatim, intro):
> The **Mesh Memory Protocol** (MMP, [arXiv:2604.19540](https://arxiv.org/abs/2604.19540)) specifies and demonstrates in its own reference implementations a typed, semantically-merged, cross-session shared memory for LLM agents; it is the closest prior art on the *mechanics* the plan's substrate needs. […] MMP coordinates *knowledge* between agents and has no concept of work, tasks, or scheduling.

**Doc passage as currently written** (verbatim, "closest prior art" subsection):
> MMP solves cross-session agent-to-agent knowledge sharing. Its four primitives are a fixed seven-field typed schema (CAT7) for a "Cognitive Memory Block" — the knowledge unit one agent passes to another; an accept-field-by-field rule, where a receiver decides field by field what to take from a peer; inter-agent lineage, so every claim is traceable to its source; and remix, where a receiver stores its own role-evaluated understanding of what it accepted.

**What the source actually says** (abstract):
> Four primitives: **CAT7** (fixed seven-field schema for Cognitive Memory Blocks); **SVAF** (role-indexed anchor evaluation realizing field-level acceptance); **inter-agent lineage** (parent/ancestor tracking via content-hash keys); **remix** (storage of role-evaluated understanding). Problem domain: "cross-session agent-to-agent cognitive collaboration—enabling agents to share, evaluate, and combine each other's cognitive state in real time across sessions." Concrete use cases listed: "multi-day data-generation sprints where generator, reviewer, and auditor agents coordinate in real time on overlapping batches; specialists carrying findings forward across session restarts." Production status: "specified, shipped, and running in production across three reference deployments."

**Verdict:** **mostly faithful, with one minor mischaracterization.** The lit review names the second primitive as "an accept-field-by-field rule"; MMP itself names the primitive **SVAF** — "role-indexed anchor evaluation realizing field-level acceptance" — which is more specific than a generic accept-rule. The lit review also asserts MMP "has no concept of work, tasks, or scheduling," but MMP's own example use cases describe coordination across roles (generator/reviewer/auditor) over data-generation sprints. That is coordination over *knowledge sharing*, not work scheduling, so the lit review's distinction is real — but the abstract evidence for MMP being purely knowledge-only is softer than the lit review claims.

**Substantive change proposed (rewrite for "closest prior art" subsection):**
> MMP solves cross-session agent-to-agent knowledge sharing. Its four primitives are **CAT7** (a fixed seven-field typed schema for a "Cognitive Memory Block"); **SVAF** (role-indexed anchor evaluation realizing field-level acceptance — the receiver evaluates each field against its role-indexed anchors rather than accepting or rejecting whole messages); **inter-agent lineage** (parent/ancestor tracking via content-hash keys, so every claim is traceable to its source); and **remix** (storage of role-evaluated understanding rather than raw peer signals). Use-cases the paper highlights — generator/reviewer/auditor coordination over multi-day data-generation sprints — show MMP is coordinating *knowledge* between roled agents over a task surface; the differentiation from the plan is therefore not "MMP has no work concept" but "MMP's coordination is over the knowledge units agents pass each other, not over the work itself" — the plan's task lifecycle, work scheduling that emerges from peer negotiation, and artifacts that spawn their own self-maintenance from their own wants remain outside MMP's primitives.

---

## II. Framing-anchor citations

### MAIF — [arXiv:2511.15097](https://arxiv.org/abs/2511.15097)

**Doc passage as currently written** (verbatim):
> **MAIF** (arXiv:2511.15097) names an "artifact-centric AI agent paradigm where behavior is driven by persistent data artifacts," so the plan cannot claim that phrasing as unprecedented. […] MAIF fuses *verification* into the data layer, not agency.

**What the source actually says** (abstract):
> Uses the exact phrase "artifact-centric AI agent paradigm where behavior is driven by persistent, verifiable data artifacts rather than ephemeral tasks." Primary focus: "trustworthiness problem at the data architecture level" through "audit trails, provenance tracking," regulatory compliance (EU AI Act). The "production-ready" claim is a throughput benchmark ("2,720.7 MB/s streaming, 1,342 MB/s video processing"), not a deployed-with-users claim.

**Verdict:** faithful. The lit review's framing (verification-not-agency; "production-ready" as throughput benchmark not deployment) matches what the abstract says.

**Substantive change proposed:** none required. (Optional tightening: the lit review currently truncates the phrase to "persistent data artifacts"; MAIF's exact phrase is "persistent, verifiable data artifacts rather than ephemeral tasks" — adding the missing "verifiable" and "rather than ephemeral tasks" makes the precedent-claim sharper.)

---

### CodeCRDT — [arXiv:2510.18893](https://arxiv.org/abs/2510.18893)

**Doc passage as currently written** (verbatim, B§2):
> **CodeCRDT (arXiv:2510.18893, 2025)** — multiple LLM agents generate code concurrently into a CRDT-backed shared state, coordinating by monitoring observable updates rather than message passing. […] across 600 trials, parallel coordination produced up to a 21% speedup on some tasks and a 39% slowdown on others, and semantic conflicts persisted in 5–10% of cases despite the CRDT guaranteeing identical copies.

**What the source actually says** (abstract):
> "lock-free, conflict-free concurrent code generation with strong eventual consistency"; 600 trials (6 tasks × 50 runs per mode); "up to 21.1% speedup on some tasks" and "up to 39.4% slowdown on others"; "semantic conflict rates (5–10%)" alongside "100% convergence with zero merge failures." The abstract reports the rate but does not define "semantic conflict" — full text needed to characterize the construct precisely.

**Verdict:** faithful on the numbers (21%, 39%, 5–10%, 600 trials). **Under-characterizes one nuance:** the lit review reads "5–10% semantic conflicts" as a property of code merges that *generalizes* to "prose-and-task artifacts" with a coverage-gap caveat. That caveat is already in the lit review's coverage-gaps section, so this is faithful but worth re-emphasizing in §B2's text.

**Substantive change proposed:** none required. (The coverage-gap caveat — that the rate is specifically for code-merge conflicts and may differ for prose/task artifacts — is already in the lit review's coverage-gaps list.)

**Caveat for follow-up:** the construct "semantic conflict" is not defined in the abstract; a full-text read of CodeCRDT would be prudent before the lit review's "the judgment layer has real work to do" inference rests on the 5–10% figure carrying the intended meaning.

---

### "Drop the Hierarchy and Roles" — [arXiv:2603.28990](https://arxiv.org/abs/2603.28990)

**Doc passage as currently written** (verbatim, B§5):
> a controlled study, not a system, running 25,000+ task runs across 8 models, 4–256 agents, 8 coordination protocols, and 4 complexity levels […]
> - Groups of LLM agents […] spontaneously invent organizational structure (5,006 distinct roles invented by just 8 agents) […]
> - A *hybrid* — fixed agent ordering, autonomous role selection — beat fully-autonomous coordination by 44% and centralized coordination by 14%
> - […] "is a privilege of strong models. Below a capability threshold ... autonomy reverses and hurts performance for weaker models." […] open-source models reaching 95% of closed-source quality at 24x lower cost.

**What the source actually says** (abstract):
> "25,000-task computational experiment spanning 8 models, 4–256 agents, and 8 coordination protocols" — the **"4 complexity levels"** detail is **not in the abstract**.
> "producing 5,006 unique roles from just 8 agents" — confirmed.
> "outperforms centralized coordination by 14% (p<0.001)" — confirmed; "with a 44% quality spread between protocols" — **confirmed but the 44% is the *spread between protocols*, not specifically the hybrid-beats-fully-autonomous figure** as the lit review currently reads it.
> "strong models self-organize effectively, while models below a capability threshold still benefit from rigid structure" — confirmed.
> "open-source achieving 95% of closed-source quality at 24x lower cost" — confirmed.

**Verdict:** **partially over-characterizes.** Two issues:
1. The "4 complexity levels" detail is not in the abstract. Either the lit review picked it up from the paper body (likely fine, just unverifiable here) or it is unsupported. **Flag for follow-up full-text check.**
2. The "44% hybrid over fully-autonomous" framing is more precise than the abstract licenses — the abstract describes "a 44% quality spread between protocols," which is consistent with but does not directly state the specific hybrid-versus-fully-autonomous gap. The 14% over centralized *is* explicit. **The 44% framing needs full-text verification.**

**Substantive change proposed (rewrite for B§5 — soften the 44%):**
> - A *hybrid* — fixed agent ordering, autonomous role selection — outperforms centralized coordination by 14% (p<0.001), and the spread between coordination protocols was 44% in quality: some imposed structure beats none. This challenges pure self-organization.

**Caveat for follow-up:** the lit review's "44% hybrid-over-fully-autonomous" reading should be checked against the paper body before the next cycle. The 14%-over-centralized figure is solidly grounded in the abstract.

---

### SwarmSys — [arXiv:2510.10047](https://arxiv.org/abs/2510.10047)

**Doc passage as currently written** (verbatim, B§5):
> **SwarmSys (arXiv:2510.10047, 2025)** is "a closed-loop framework that enables LLM agents to coordinate through lightweight, pheromone-like traces ... without centralized control." […] but SwarmSys is a coordination architecture studied in isolation and stops at coordination.

**What the source actually says** (abstract):
> "closed-loop framework for distributed multi-agent reasoning inspired by swarm intelligence"; "Coordination in SwarmSys emerges through iterative interactions among three specialized roles, Explorers, Workers, and Validators"; "a pheromone-inspired reinforcement mechanism"; "self-organizing convergence without global supervision"; evaluated "across symbolic reasoning, research synthesis, and scientific programming tasks." The roles in SwarmSys are pre-specified (Explorer, Worker, Validator), not emergent.

**Verdict:** **partially mischaracterizes.** The lit review's "lightweight, pheromone-like traces ... without centralized control" is rough but accurate. The lit review omits a substantive nuance: SwarmSys uses **pre-specified roles** (Explorer/Worker/Validator), which makes it less "self-organizing without structure" than the lit review's framing implies. The differentiation from the plan is therefore stronger than the current text claims (SwarmSys retains role structure), but the differentiation from "Drop the Hierarchy" is also stronger (SwarmSys does not allow agents to invent roles).

**Substantive change proposed (rewrite for B§5):**
> **SwarmSys (arXiv:2510.10047, 2025)** is a closed-loop framework where LLM agents coordinate through a pheromone-inspired reinforcement mechanism without centralized control. Coordination is distributed across three pre-specified roles (Explorers, Workers, Validators) cycling through exploration, exploitation, and validation. The decentralized, stigmergic coordination is close to the plan's headline, but SwarmSys is a coordination architecture studied in isolation, with a fixed role structure (its self-organization is at the task-allocation layer, not the role layer), and it stops at coordination. The plan's claim is that the *artifact itself* should be the unit, that role assignment is itself a negotiable, and that coordination is what *emerges* when artifacts of that kind interact.

---

### Agora-Opt — [arXiv:2604.25847](https://arxiv.org/abs/2604.25847)

**Doc passage as currently written** (verbatim, B§5):
> **"From Soliloquy to Agora" (Agora-Opt, [arXiv:2604.25847](https://arxiv.org/abs/2604.25847), 2026)** is an agentic framework scoped to *optimization modeling*. Multiple agent teams each produce an end-to-end solution independently, reconciled through an "outcome-grounded debate protocol" scored against verifiable solver outcomes, with a read-write memory bank of solver-verified artifacts.

**What the source actually says** (abstract):
> Domain: "optimization modeling" for "real-world decision-making in logistics, manufacturing, energy, and public services." Framework reconciles candidate solutions "through an outcome-grounded debate protocol." Memory bank "stores solver-verified artifacts" and "past disagreement resolutions." Abstract does not elaborate on debate-protocol mechanics.

**Verdict:** faithful. The lit review's framing — decentralized, solver-oracle-grounded, agent-centric not artifact-centric — matches the abstract.

**Substantive change proposed:** none required.

---

### Semantic Consensus — [arXiv:2604.16339](https://arxiv.org/abs/2604.16339)

**Doc passage as currently written** (verbatim, B§5):
> **Semantic Consensus** (arXiv:2604.16339, 2026) formally treats it, defining "Semantic Intent Divergence" […] citing production failure rates of 41–86.7%. It proposes a Semantic Consensus Framework with a conflict-detection engine and a drift monitor. […] process-aware middleware over the agents.

**What the source actually says** (abstract):
> "identifies Semantic Intent Divergence--the phenomenon whereby cooperating LLM agents develop inconsistent interpretations of shared objectives"; "production deployments exhibit failure rates between 41% and 86.7%"; "Semantic Consensus Framework (SCF)" with "a Conflict Detection Engine" and "a Drift Monitor for detecting gradual semantic divergence"; "process-aware middleware"; evaluated across "three multi-agent frameworks (AutoGen, CrewAI, LangGraph)."

**Verdict:** faithful — every cited element is present in the abstract.

**Substantive change proposed:** none required.

**Alternative perspective the lit review does not represent:** Semantic Consensus tests against three *existing* multi-agent frameworks (AutoGen, CrewAI, LangGraph), all orchestrator-centric. Its "41–86.7% production failure rate" figure is therefore conditional on that frame — it is not a universal property of multi-agent LLM systems, and how it generalizes to the plan's artifact-centric substrate is open. The lit review uses the figure rhetorically in B§5's "human-at-boundary" discussion; the framing could be tightened to "41–86.7% failure across three orchestrator-centric multi-agent frameworks" to avoid the implicit claim that this is the universal rate.

---

## III. Blackboard cluster

### Han & Zhang (LLM blackboard) — [arXiv:2507.01701](https://arxiv.org/abs/2507.01701)

**Doc passage as currently written** (verbatim, B§1):
> Han & Zhang (arXiv:2507.01701, 2025) gave the first LLM implementation of the classical blackboard — agents share messages on a board, a selection step picks who acts, rounds repeat until consensus — competitive with state-of-the-art at lower token cost.

**What the source actually says** (abstract):
> Proposes "incorporat[ing] the blackboard architecture into LLM multi-agent systems (MASs)" so that "(1) agents […] share all the information and others' messages […], (2) agents that will take actions are selected based on the current content of the blackboard, and (3) the selection and execution round is repeated until a consensus is reached." "Develop the first implementation of this proposal." "Best average performance" while spending "less tokens" than SOTA static and dynamic approaches.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### Salemi et al. (LLM-blackboard for data discovery) — [arXiv:2510.01285](https://arxiv.org/abs/2510.01285)

**Doc passage as currently written** (verbatim, B§1 / intro to Appendix):
> Salemi et al. (arXiv:2510.01285, 2025) apply the pattern to data discovery with 13–57% relative gains. […] Retains a central agent that posts requests — it decentralizes only the capability knowledge a coordinator would need, not the central node.

**What the source actually says** (abstract):
> "13%–57% relative improvements in end-to-end success"; "a central agent posts requests to a shared blackboard, and autonomous subordinate agents […] volunteer to respond based on their capabilities."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

## IV. Self-organization stress-tests

### "Consensus Trap" — [arXiv:2604.17139](https://arxiv.org/abs/2604.17139)

**Doc passage as currently written** (verbatim, B§5):
> the "Consensus Trap" (arXiv:2604.17139, 2026) shows majority-vote aggregation collapsing under a corrupted local majority

**What the source actually says** (abstract):
> "response-level aggregation collapses when corrupted agents form a local majority"; "while MAJ [majority voting] collapses when corrupted agents reach a majority, RR maintains robust accuracy well beyond this critical threshold." "Consensus Trap" appears only in the title; the paper itself uses "response-level aggregation" and "structural vulnerability."

**Verdict:** **mildly over-characterizes** by treating "Consensus Trap" as the paper's formal term. The paper's substantive theoretical content is "response-level aggregation collapse"; "Consensus Trap" is the descriptive title only.

**Substantive change proposed (minor tightening for B§5):**
> Recent multi-agent work names concrete failure modes — e.g. the paper titled "The Consensus Trap" (arXiv:2604.17139, 2026) shows response-level aggregation (majority voting) collapses when corrupted agents form a local majority, while round-robin aggregation maintains accuracy past the corruption threshold; the plan's timeout-into-dropped rule is one mitigation among several and is untested here.

---

## V. Position papers and adjacent visions

### Ψ-Arch — [arXiv:2604.13934](https://arxiv.org/abs/2604.13934)

**Doc passage as currently written** (verbatim, B§4):
> A 2026 position paper, **Ψ-Arch (arXiv:2604.13934)**, proposes "autopoietic architectures" — software that self-constructs and self-maintains via a foundation-model reasoning unit — but as an aspirational single-program direction, not a built system, and with no concurrency, peer negotiation, or in-flight state

**What the source actually says** (abstract):
> Explicitly a "Positional Paper" exploring Psi-Arch as "a foundational framework for self-constructing software." "Although this paper does not present a definitive solution, it seeks to catalyze discourse and inspire research toward a new paradigm." The abstract does not address concurrency, peer negotiation, or in-flight state mechanisms either way.

**Verdict:** **faithful on the position-paper / aspirational framing**, but the "no concurrency, no peer negotiation, no in-flight state" sub-claims are stronger than the abstract licenses — the abstract is silent on these aspects rather than denying them. The lit review should soften from "with no concurrency, peer negotiation, or in-flight state" to "the abstract does not engage concurrency, peer negotiation, or in-flight state."

**Substantive change proposed (rewrite for B§4):**
> A 2026 position paper, **Ψ-Arch (arXiv:2604.13934)**, proposes "autopoietic architectures" — software that self-constructs and self-maintains via a foundation-model reasoning unit — but as an aspirational positional paper, not a built system; concurrency, peer negotiation, and in-flight state are not addressed in the proposal; the plan applies the same self-maintenance aspiration to a population of negotiating artifacts.

---

### LSS (Loosely-Structured Software) — [arXiv:2603.15690](https://arxiv.org/abs/2603.15690)

**Doc passage as currently written** (verbatim, B§4):
> **LSS (arXiv:2603.15690)** names "Endogenous Evolution" — behavior-shaping files the multi-agent system rewrites — so "artifacts that get rewritten" is not unprecedented; but LSS's artifacts are the medium agents rewrite, where the plan puts the agency in the artifact itself.

**What the source actually says** (abstract):
> Proposes "Loosely-Structured Software (LSS), a new class of software systems" with a three-layer framework: "View/Context Engineering," "Structure Engineering," and "Evolution Engineering." The phrase "endogenous evolution" appears only in passing ("semantic-driven self-organization, and endogenous evolution"), **not formally named as a distinct concept** in the abstract. The abstract describes "self-rewriting artifacts" and "dynamic binding over artifacts and agents" but doesn't fully clarify whether the artifacts are agents themselves.

**Verdict:** **over-characterizes the terminology claim.** "Endogenous Evolution" is not the formally-named concept the lit review treats it as — it appears only in passing in the abstract. The architectural framing the paper itself names is "Evolution Engineering," one of three engineering layers. The "artifacts are the medium agents rewrite, not the agency-bearer" reading is consistent with the abstract.

**Substantive change proposed (rewrite for B§4):**
> **LSS (arXiv:2603.15690)** proposes a three-layer framework including "Evolution Engineering" to govern the lifecycle of self-rewriting artifacts — so "artifacts that get rewritten" is not unprecedented; but in LSS the agency sits with the agents rewriting the files, where the plan puts the agency in the artifact itself.

---

### MemoRepair — [arXiv:2605.07242](https://arxiv.org/abs/2605.07242)

**Doc passage as currently written** (verbatim, references list):
> [MemoRepair] Formalizes the "cascade update problem" and repairs it with a centralized, deterministic recomputation over every downstream artifact, eliminating invalidated-memory exposure.

**Doc passage as currently written** (verbatim, B§5):
> MEMOREPAIR (arXiv:2605.07242, 2026) formalizes the stale-derived-artifact problem as the "cascade update problem" and solves it with a centralized, deterministic recomputation that traces every downstream artifact and repairs it in one pass; the plan's self-maintenance is the decentralized, judgment-resolved counterpart.

**What the source actually says** (abstract):
> "formalize this failure mode as the cascade update problem, where repair targets the visible derived state of the memory store." The method is a **"barrier-first cascade-repair contract"**: "withdrawing affected descendants before repair," "constructing successors from retained support and staged repaired predecessors," and "restricting republication to validated predecessor-closed successors." It "reduces the repair problem to a maximum-weight predecessor closure problem solved by s-t min-cut." It is **not** "centralized, deterministic recomputation of every downstream artifact" — it is a min-cut-based selective closure, which is more sophisticated than the recompute-everything framing the lit review describes.

**Verdict:** **mischaracterizes the mechanism.** The lit review describes MemoRepair as "centralized, deterministic recomputation traces every downstream artifact" — but the actual mechanism is a min-cut-based selective predecessor-closure repair, not a brute-force recomputation. The high-level "decentralized vs. centralized" distinction the lit review uses to contrast with the plan is approximately right (the plan's approach is decentralized peer negotiation, MemoRepair's is a globally-coordinated barrier-then-repair protocol). But the description of the mechanism is wrong on the technical detail.

**Substantive change proposed (rewrite for references list):**
> [MemoRepair] Formalizes the "cascade update problem" for stale derived artifacts in agentic memory and solves it with a "barrier-first cascade-repair contract" that withdraws affected descendants, constructs successors from retained support and staged repaired predecessors, and reduces the repair scope to a maximum-weight predecessor closure problem (solved by s-t min-cut) rather than recomputing every descendant.

**Substantive change proposed (rewrite for B§5):**
> MemoRepair (arXiv:2605.07242, 2026) formalizes the stale-derived-artifact problem as the "cascade update problem" and solves it with a globally-coordinated barrier-first repair protocol — affected descendants are withdrawn, successors are constructed from retained support and staged repaired predecessors, and the repair scope is reduced to a maximum-weight predecessor closure problem (s-t min-cut). The mechanism is selective rather than exhaustive recomputation, but the coordination is global and the resolution is deterministic. The plan's self-maintenance is the decentralized, judgment-resolved counterpart: each artifact carries its own integrity-maintenance task and negotiates as a peer rather than yielding to a global barrier-then-closure protocol.

---

## VI. Evolutionary-computation cluster

### CORAL — [arXiv:2604.01658](https://arxiv.org/abs/2604.01658)

**Doc passage as currently written** (verbatim, B§6):
> CORAL (arXiv:2604.01658, 2026) builds autonomous agents that run an evolutionary loop's operators, which narrows the gap but not the sliver: the unclaimed element is selection emerging from the candidates themselves, not autonomous agents operating the loop's machinery.

**What the source actually says** (abstract):
> "autonomous multi-agent evolution on open-ended problems" with "long-running agents that explore, reflect, and collaborate through shared memory and asynchronous execution." Whether selection is internal or external is not made clear by the abstract — emphasis on "agent autonomy" and agents that "explore, reflect, and collaborate" suggests internal agency in decision-making, but "external evaluators are mentioned as practical safeguards" suggests hybrid involvement.

**Verdict:** **under-characterizes one nuance and over-characterizes another.** The abstract is more ambiguous than the lit review allows: the abstract says agents explore-reflect-collaborate (which could be read as candidates participating in their own selection) *and* mentions external evaluators (which makes selection at least partly external). The flat assertion "selection emerging from the candidates themselves [is] the unclaimed sliver" therefore needs a small softening: CORAL is in the *direction* of internal candidate participation, just not all the way there. The "autonomous agents operating the loop's machinery" framing might understate CORAL's agency.

**Substantive change proposed (rewrite for B§6):**
> CORAL (arXiv:2604.01658, 2026) builds long-running agents that run an evolutionary loop's operators, exploring, reflecting, and collaborating through shared memory and asynchronous execution; external evaluators provide safeguards. It moves in the direction of agent-participated selection but does not present selection as emerging from the candidates negotiating their own survival peer-to-peer. *Negotiated internal selection* — candidates that evaluate their own fitness in context and negotiate survival with neighbors with no external selector — remains the unclaimed sliver. Whether it produces useful evolutionary pressure is untested.

---

### A-Evolve — [arXiv:2602.00359](https://arxiv.org/abs/2602.00359)

**Doc passage as currently written** (verbatim, B§6):
> **"Agentic Evolution is the Path to Evolving LLMs" (arXiv:2602.00359)**, proposes *A-Evolve* — evolution reframed as goal-directed optimization over persistent system state. It is a fifth data point that the passive-genome and external-loop pillars are eroding, but it is single-system self-improvement, not a population of living units negotiating their own selection.

**What the source actually says** (abstract):
> Position paper. "treats deployment-time improvement as a deliberate, goal-directed optimization process over persistent system state"; "autonomous evolver agent" managing adaptation within a single deployed system's persistent state.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### AlphaEvolve — [arXiv:2506.13131](https://arxiv.org/abs/2506.13131)

**Doc passage as currently written** (verbatim, B§6):
> **AlphaEvolve (Google DeepMind, 2025, [arXiv:2506.13131](https://arxiv.org/abs/2506.13131))** is an evolutionary coding agent that improved on a 1969 matrix-multiplication result and found a data-center scheduling heuristic in production use.

**What the source actually says** (abstract):
> "developed a search algorithm that found a procedure to multiply two 4×4 complex-valued matrices using 48 scalar multiplications; offering the first improvement, after 56 years, over Strassen's algorithm in this setting." Data-center scheduling: "developed a more efficient scheduling algorithm for data centers." The "in production use" claim is **not explicit in the abstract** — the abstract only says it was applied to Google's computational infrastructure.

**Verdict:** **mildly over-characterizes.** "Production use" is not stated in the abstract. (It is stated in the AlphaEvolve blog post and is broadly true.) This is the kind of detail where citing the blog post in addition to the arXiv reference would be defensible; otherwise tighten to "applied to data-center scheduling at Google."

**Substantive change proposed (minor tightening for B§6):**
> **AlphaEvolve (Google DeepMind, 2025, [arXiv:2506.13131](https://arxiv.org/abs/2506.13131))** is an evolutionary coding agent that improved on Strassen's 1969 result for 4×4 complex-valued matrix multiplication and developed a data-center scheduling algorithm applied at Google.

---

## VII. Other adjacent visions

### "Last Human-Written Paper" — [arXiv:2604.24658](https://arxiv.org/abs/2604.24658)

**Doc passage as currently written** (verbatim):
> **"The Last Human-Written Paper: Agent-Native Research Artifacts" (arXiv:2604.24658, 2026)** proposes machine-executable research packages with a "Live Research Manager" — adjacent to the plan's "living research workflows" direction, though it externalizes a research package rather than giving the artifact agency.

**What the source actually says** (abstract):
> "Agent-Native Research Artifact (ARA), a protocol that replaces the narrative paper with a machine-executable research package." "Live Research Manager that captures decisions and dead ends during ordinary development" is one of three supporting mechanisms. Agency resides primarily with the agent; the ARA is a structured specification.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### "Intermediate Artifacts as First-Class Citizens" — [arXiv:2605.12087](https://arxiv.org/abs/2605.12087)

**Doc passage as currently written** (verbatim, B§4):
> A 2026 data-model paper, **"Intermediate Artifacts as First-Class Citizens" (arXiv:2605.12087)**, proposes typed, versioned, dependency-aware durable intermediate artifacts — so the plan does not coin that data-model vocabulary; but its artifacts are passive completed work-products with no agency

**What the source actually says** (abstract):
> "typed, structured, addressable, versioned, dependency-aware, authoritative, and consumable by downstream computation." "These artifacts are not the model's private chain-of-thought. They are maintained work products such as evidence maps, claim structures, criteria, assumptions, plans..." Designed for "human and agent inspection, revision, and improvement."

**Verdict:** faithful.

**Substantive change proposed:** none required. (Optional: the lit review skips "addressable" and "authoritative" from the paper's vocabulary list; including them would make the precedent-claim slightly sharper.)

---

### Externalization survey — [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)

**Doc passage as currently written** (verbatim):
> "Externalization in LLM Agents" (arXiv:2604.08224, 2026) — A 54-page survey arguing modern LLM agents are built by externalizing capability into memory, skills, protocols and harness rather than by changing weights

**What the source actually says** (abstract):
> "Large language model (LLM) agents are increasingly built less by changing model weights than by reorganizing the runtime around them. Capabilities that earlier systems expected the model to recover internally are now externalized into memory stores, reusable skills, interaction protocols, and the surrounding harness." 54 pages confirmed.

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### InfiAgent — [arXiv:2601.03204](https://arxiv.org/abs/2601.03204)

**Doc passage as currently written** (verbatim, references):
> [InfiAgent] Bounds a single long-horizon agent's reasoning context by externalizing persistent state into a file-centric state abstraction; passive externalized memory, not multi-party authoritative state.

**What the source actually says** (abstract):
> "keeps the agent's reasoning context strictly bounded regardless of task duration by externalizing persistent state into a file-centric state abstraction."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

### "Everything is Context" — [arXiv:2512.05470](https://arxiv.org/abs/2512.05470)

**Doc passage as currently written** (verbatim):
> [Everything is Context] A file-system abstraction for context engineering — persistent, governed, human-curated context infrastructure; passive infrastructure, not an artifact with agency.

**What the source actually says** (abstract):
> "Generative AI (GenAI) has reshaped software system design." Proposes a "file-system abstraction for context engineering, inspired by the Unix notion that 'everything is a file'." Includes active components: "Context Constructor, Loader, and Evaluator that assemble and validate context."

**Verdict:** **mildly under-characterizes.** The "passive infrastructure" framing is approximately right (it is infrastructure, not an agent), but the abstract names active components — Context Constructor, Loader, and Evaluator — that do active work over the file-system context. So "passive infrastructure" is too flat.

**Substantive change proposed (rewrite for references):**
> [Everything is Context] A file-system abstraction for context engineering — persistent, governed, human-curated context infrastructure with active assembler/loader/evaluator components; infrastructure rather than an artifact with agency.

---

### CollabDoc — [arXiv:2509.11826](https://arxiv.org/abs/2509.11826)

**Doc passage as currently written** (verbatim, B§2):
> **"Collaborative Document Editing with Multiple Users and AI Agents" (arXiv:2509.11826, 2025)** — "the first to investigate how multiple people work together with multiple shared AI agents within a shared document environment," with agent profiles and tasks as shared objects.

**What the source actually says** (abstract):
> "Current AI writing support tools are largely designed for individuals." Proposes "integrating AI agents directly into collaborative writing environments." Two novel interface elements: "user-defined agent profiles and tasks" as shared objects. **The abstract does not contain the verbatim "the first to investigate" phrase as the lit review quotes.**

**Verdict:** **mischaracterizes — quoted phrase not verifiable in the abstract.** The lit review presents "the first to investigate how multiple people work together with multiple shared AI agents within a shared document environment" as a verbatim quote. The abstract does not contain that exact phrase. The novelty framing is consistent with the abstract's "current tools are designed for individuals" framing, but the quote attribution is incorrect. **This is a verifiable factual error in the lit review.**

**Substantive change proposed (rewrite for B§2):**
> **"Collaborative Document Editing with Multiple Users and AI Agents" (arXiv:2509.11826, 2025)** — proposes integrating AI agents directly into collaborative writing environments, with user-defined agent profiles and tasks as shared objects within the document. The paper positions itself as filling a gap in current AI writing tools, which are designed for individual rather than multi-user-multi-agent collaboration. Structurally the plan's "artifact contains its task queue."

**Caveat for follow-up:** the lit review should either remove the quotation marks and rephrase, or locate the verbatim "the first to investigate" passage in the paper's body and cite it with section reference. Quoted text that isn't a verbatim quote is a citation hygiene failure.

---

### TheBotCompany — [arXiv:2603.25928](https://arxiv.org/abs/2603.25928)

**Doc passage as currently written** (verbatim, B§4):
> **TheBotCompany** (arXiv:2603.25928, 2026) is the same shape: a three-phase state machine in which manager agents "dynamically hire, assign, and fire worker agents" — a manager hierarchy with central control, experimentally evaluated, not deployed.

**What the source actually says** (abstract):
> "three-phase state machine (Strategy to Execution to Verification) for milestone-driven development"; "self-organizing agent teams where manager agents dynamically hire, assign, and fire worker agents based on project needs"; "asynchronous human oversight."

**Verdict:** faithful — but the paper itself calls the agent teams "self-organizing" (a framing the lit review pushes back on as "manager hierarchy with central control"). The lit review's reading — manager-with-workers is still a hierarchy, even if the manager is itself an LLM — is defensible, but acknowledging the paper's own self-organization framing would be intellectually honest.

**Substantive change proposed (minor sharpening for B§4):**
> **TheBotCompany** (arXiv:2603.25928, 2026) describes its agent teams as "self-organizing," but the structure is a manager-hires-fires-workers hierarchy over a three-phase state machine (Strategy → Execution → Verification) — the self-organization is in the dynamic team composition, not in the absence of a manager hierarchy. Experimentally evaluated, not deployed.

---

### AgentsNet — [arXiv:2507.08616](https://arxiv.org/abs/2507.08616)

**Doc passage as currently written** (verbatim, B§5):
> **AgentsNet (arXiv:2507.08616)** is a benchmark for multi-agent self-organization, scalable to 100 agents — a ready-made yardstick the plan's later PRs could measure against.

**What the source actually says** (abstract):
> Measures "the ability of multi-agent systems to collaboratively form strategies for problem-solving, self-organization, and effective communication given a network topology." Drawn from "classical problems in distributed systems and graph theory." "Practically unlimited in size"; probes "up to 100 agents."

**Verdict:** faithful.

**Substantive change proposed:** none required.

---

## VIII. Classical lineage (lighter check)

These citations are well-attested in standard secondary literature; the audit here is a lighter sanity check against the lit review's own characterizations, not a full-text read.

### Hewitt 1973 / Agha 1986 (actor model)

**Lit-review claim:** Actor model is decentralized (no central scheduler); per-actor behavior is a fixed program; "intelligence" of an actor is whatever a programmer wrote into it ahead of time.

**Standard secondary characterization (SEP, Wikipedia, distributed-systems textbooks):** All three claims match. The actor model is famously decentralized (no shared memory, no global clock); actor behavior is a finite specification of what to do with each kind of incoming message. The lit review's framing — "the plan's move is to replace that fixed program with an LLM" — is fair.

**Verdict:** faithful. The lit review explicitly flags Agha 1986 as not full-text-read (B§7's coverage-gaps note), which is the correct disclosure.

---

### Smith 1980 (contract-net)

**Lit-review claim:** Distributed problem-solving via announce-bid-award; task allocation, not content negotiation.

**Standard secondary characterization:** Matches.

**Verdict:** faithful.

---

### Hearsay-II / Nii 1986 (blackboard)

**Lit-review claim:** Blackboard architecture; multiple knowledge sources read/write a shared workspace; **central control component decides each cycle which knowledge source runs next.**

**Standard secondary characterization:** Matches. The "control component" in Hearsay-II and in Nii's survey is exactly the lit review's "central scheduler" claim.

**Verdict:** faithful. (Coverage-gaps note in the lit review correctly flags Nii 1986 as not full-text-read.)

---

### Gelernter 1985 / Carriero & Gelernter (Linda)

**Lit-review claim:** Tuple space; coordination through a shared content-addressable pool; out/rd/in primitives; decentralized.

**Standard secondary characterization:** Matches.

**Verdict:** faithful.

---

### Ellis & Gibbs 1989 (OT)

**Lit-review claim:** OT for concurrent document editing; original (1989) technique; engine behind Google Docs.

**Standard secondary characterization:** Matches.

**Verdict:** faithful.

---

### Shapiro et al. 2011 (CRDT)

**Lit-review claim:** CRDTs guarantee independent copies converge once they exchange updates; no central coordinator; mathematical guarantee on syntactic convergence.

**Standard secondary characterization:** Matches.

**Verdict:** faithful.

---

### Engelbart 1962/1968, Knuth 1984, Minsky 1986

**Lit-review claims:** Engelbart (NLS, augmentation, dynamic-manipulable-document vision); literate programming (Knuth, program-as-prose); Society of Mind (Minsky, intelligence-from-simple-agents).

**Standard secondary characterization:** All match. The lit review's framings are standard.

**Verdict:** faithful.

---

## IX. Supporting / lighter citations

### MemGPT — [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)

**Lit-review claim:** Treats LLM as OS managing memory between context window and external storage.

**Source (abstract):** Confirms "virtual context management, a technique drawing inspiration from hierarchical memory systems in traditional operating systems that provide the appearance of large memory resources through data movement between fast and slow memory."

**Verdict:** faithful.

---

### AutoGen — [arXiv:2308.08155](https://arxiv.org/abs/2308.08155)

**Lit-review claim:** "Group chat" mode runs through a central "group chat manager" that decides who speaks next — a central arbiter.

**Source (abstract):** The abstract emphasizes "developers can flexibly define agent interaction behaviors" and "natural language and computer code can be used to program flexible conversation patterns" — the group-chat-manager detail is not in the abstract itself, and AutoGen's group chat manager is in fact customizable (a developer can program it to be more or less directive).

**Verdict:** **mildly over-characterizes.** AutoGen has a group chat manager component, but the lit review's framing as "a central arbiter [that] decides who speaks next" reads as universally directive; in practice AutoGen's group chat manager can be programmed to round-robin, use an LLM to select, or follow custom logic. The "central arbiter" reading is fair for *the most directive configuration*, but AutoGen as a *framework* is more flexible than the lit review's single-line description implies.

**Substantive change proposed (minor tightening for B§4):**
> **AutoGen** (Wu et al., 2023) is Microsoft's multi-agent conversation framework. Its "group chat" mode runs through a group-chat-manager component that, in its standard configuration, decides who speaks next (configurable to LLM-based selection, round-robin, or custom logic) — a central decision point even when the policy is configurable.

---

### MetaGPT — [arXiv:2308.00352](https://arxiv.org/abs/2308.00352)

**Lit-review claim:** Encodes fixed Standard Operating Procedures (Product Manager → Architect → Engineer) pre-designed by humans.

**Source (abstract):** Confirms "MetaGPT encodes Standardized Operating Procedures (SOPs) into prompt sequences for more streamlined workflows." The specific Product-Manager → Architect → Engineer ordering is widely documented in the paper body and in the GitHub README, but is not in the abstract.

**Verdict:** faithful at the SOP claim; the specific role ordering is paper-body-level and widely-attested.

---

### ChatDev (Qian et al. 2024)

**Lit-review claim:** Fixed 7-role pipeline.

**Standard secondary characterization:** Matches widely-cited ChatDev description.

**Verdict:** faithful (not independently fetched in this audit).

---

### Promptbreeder (Fernando et al. 2024)

**Lit-review claim:** Evolves a population of prompts with LLM-generated mutation operators that themselves evolve.

**Standard secondary characterization:** Matches.

**Verdict:** faithful (not independently fetched).

---

### FunSearch (Romera-Paredes et al. 2023, *Nature*)

**Lit-review claim:** Pairs LLM with evaluator in evolutionary loop; discovered new cap-set result.

**Standard secondary characterization:** Matches.

**Verdict:** faithful (not independently fetched).

---

### ADAS (Hu et al. ICLR 2025)

**Lit-review claim:** Meta-agent evolves agentic systems themselves from a growing archive.

**Standard secondary characterization:** Matches.

**Verdict:** faithful (not independently fetched).

---

### Lehman & Stanley 2011 (novelty search)

**Lit-review claim:** Abandons objective fitness; selects for behavioral novelty; outperforms objective-based search on deceptive problems.

**Standard secondary characterization:** Matches.

**Verdict:** faithful (not independently fetched).

---

### Industry / blog sources (Karpathy LLM-OS; Carvalho "Reinventing Linda"; Electric AI-Agents-as-CRDT-Peers; Victor / Dynamicland)

These are stylistic / inspirational citations. The lit review's framings (LLM-as-kernel; modern orchestration as rediscovered Linda; AI agents as CRDT peers; Victor's dynamic-responsive-media vision) match how these sources are widely understood. No specific load-bearing factual claim depends on them.

**Verdict:** faithful in their stylistic role.

---

## X. Summary table

### Material fixes (substantive change recommended)

| Citation | Issue | Fix |
|---|---|---|
| ScienceClaw + Infinite (arXiv:2603.14312) | Over-characterizes the agency gap; abstract says ArtifactReactor "autonomously discovers needs." | Soften: ScienceClaw's agency is distributed across agents and an artifact-reactor layer; the plan's residual narrows to artifact-as-negotiating-peer with explicit wants and task lifecycle. |
| MemoRepair (arXiv:2605.07242) | Mechanism mischaracterized as "centralized deterministic recomputation of every downstream artifact"; actual mechanism is min-cut-based selective predecessor-closure repair. | Rewrite mechanism description (selective barrier-first repair, not exhaustive recomputation). |
| CollabDoc (arXiv:2509.11826) | Quoted phrase "the first to investigate..." not verifiable in the abstract; citation hygiene failure. | Remove the quotation marks and rephrase, or locate the exact source passage and cite it with section reference. |
| LSS (arXiv:2603.15690) | "Endogenous Evolution" is not formally named; the framework's named layer is "Evolution Engineering." | Rewrite to reflect the framework's actual three-layer naming. |
| SwarmSys (arXiv:2510.10047) | Omits that SwarmSys uses pre-specified roles (Explorer/Worker/Validator). | Add the role-fixity nuance. |

### Optional tightenings (faithful but could be sharper)

| Citation | Tightening |
|---|---|
| MMP (arXiv:2604.19540) | Name SVAF (not "accept-field-by-field rule"); soften "no concept of work" to "coordination over knowledge units, not over the work itself." |
| MAIF (arXiv:2511.15097) | Include the full phrase "persistent, *verifiable* data artifacts *rather than ephemeral tasks*" for a sharper precedent claim. |
| "Drop the Hierarchy" (arXiv:2603.28990) | The "44% hybrid-over-fully-autonomous" framing is the abstract's "44% quality spread between protocols" — flag for full-text verification. The "4 complexity levels" detail is not in the abstract — flag for full-text verification. |
| "Consensus Trap" (arXiv:2604.17139) | "Consensus Trap" appears only in the title; the paper's substantive term is "response-level aggregation collapse." |
| Ψ-Arch (arXiv:2604.13934) | The abstract is silent on concurrency / peer negotiation / in-flight state (not denying them); soften the lit review's flat assertion accordingly. |
| Semantic Consensus (arXiv:2604.16339) | 41–86.7% failure rates are conditional on the three frameworks tested (AutoGen, CrewAI, LangGraph) — orchestrator-centric multi-agent systems; the framing could tighten to make that conditional explicit. |
| CodeCRDT (arXiv:2510.18893) | "Semantic conflict" is not defined in the abstract; the lit review's coverage-gap caveat covers this, but a full-text follow-up to confirm the construct's meaning would strengthen the 5–10% inference. |
| AlphaEvolve (arXiv:2506.13131) | "In production use" is not stated in the arXiv abstract; soften or cite the supporting blog post. |
| CORAL (arXiv:2604.01658) | The abstract is ambiguous on internal vs. external selection — CORAL is in the direction of internal-candidate-participation, not flatly external. |
| AutoGen | "Central arbiter" framing is too flat for AutoGen's configurable group-chat-manager; tighten to "a central decision point, even when the selection policy is configurable." |
| "Everything is Context" (arXiv:2512.05470) | Note its active components (Constructor, Loader, Evaluator), not just "passive infrastructure." |
| TheBotCompany (arXiv:2603.25928) | The paper itself uses "self-organizing"; acknowledge that framing while pushing back on it for the manager hierarchy. |

### Faithful (no change required)

AgentNet (arXiv:2504.00587); CodeCRDT (numeric figures); Agora-Opt (arXiv:2604.25847); Semantic Consensus (arXiv:2604.16339, modulo the framing-tightening); Han & Zhang blackboard (arXiv:2507.01701); Salemi LLM-blackboard (arXiv:2510.01285); A-Evolve (arXiv:2602.00359); "Last Human-Written Paper" (arXiv:2604.24658); Intermediate Artifacts (arXiv:2605.12087); Externalization survey (arXiv:2604.08224); InfiAgent (arXiv:2601.03204); AgentsNet (arXiv:2507.08616); MemGPT (arXiv:2310.08560); MetaGPT (at the SOP claim); Hewitt 1973 / Agha 1986; Smith 1980; Hearsay-II / Nii 1986; Gelernter 1985 / Linda; Ellis & Gibbs 1989; Shapiro 2011; Engelbart 1962/1968; Knuth 1984; Minsky 1986; ChatDev, Promptbreeder, FunSearch, ADAS, novelty search (light/secondary).

---

## XI. Fetch failures and scope notes

**Successfully abstract-fetched:** all 25 priority arXiv citations.

**Not full-text-fetched in this pass (abstract only):** every entry on the priority list. For the load-bearing entries above flagged "needs full-text follow-up," a future pass should fetch and read:
- CodeCRDT — confirm what "semantic conflict" means at construct level.
- "Drop the Hierarchy" — verify the "44% hybrid-over-fully-autonomous" precise mapping; verify "4 complexity levels."
- MemoRepair — the abstract has enough to fix the lit review's mechanism description, but the full text would let us state the repair mechanism more precisely.
- CollabDoc — locate (or refute) the "first to investigate" verbatim passage.

**Not fetched (classical / secondary literature):** Hewitt 1973, Agha 1986, Smith 1980, Hearsay-II, Nii 1986, Gelernter 1985, Carriero & Gelernter 1992, Ellis & Gibbs 1989, Shapiro 2011, Engelbart 1962/1968, Knuth 1984, Minsky 1986. The lit review's coverage-gaps section already notes Agha 1986 / Nii 1986 / Dias 2006 as abstract-and-secondary characterizations; this audit confirms that disclosure.

**Not independently fetched (supporting):** Promptbreeder, FunSearch, ADAS, ChatDev, novelty search, the industry blog sources. Their roles in the lit review are stylistic / inspirational, and standard secondary characterizations match what the lit review says.

**Companion audit:** the persona / role-prompting citations (Salewski 2023, Deshpande 2023, Gupta 2023) are audited in the companion `CITATION_AUDIT_USERMODEL_EXTENSION.md`; the Appendix B §7 framing in the living-artifacts review draws on that companion review.

---

## XII. Alternative perspectives the lit review does not represent

A handful of caveats and alternative readings live in the cited sources that the lit review does not surface.

1. **The "blackboard revival" papers (Han & Zhang 2507.01701, Salemi 2510.01285) both retain selection steps.** The lit review treats these as evidence that the blackboard pattern is being revived "for LLM agents" and contrasts them with the plan's artifact-as-agent. A subtler reading: both revivals keep the *Hearsay-II selection-step pattern* (a controller picks who acts next); they do not test whether the selection step is needed at all. The plan's removal of central selection is therefore further from the blackboard revival than the surface-similar pattern suggests — a point worth making more strongly in B§1.

2. **CodeCRDT's slowdown finding cuts both ways.** The lit review uses CodeCRDT's 5–10% semantic conflict rate as evidence the judgment layer has work to do, and the 21% speedup as support for parallel coordination. The 39% slowdown — that parallel coordination can be *worse* — is mentioned but not engaged: the plan's distributed-task model bets that parallelism is net positive, and CodeCRDT's evidence is mixed on whether that holds.

3. **"Drop the Hierarchy" finds hybrid > fully-autonomous.** The lit review surfaces this as one of three findings and adjusts the plan's "no central arbiter" framing accordingly. But the strong reading of "Drop the Hierarchy" — that some imposed structure beats no imposed structure even with strong models — is in tension with the plan's "tasks negotiate peer-to-peer" framing more deeply than the current B§5 text engages. The plan's "humans (and watchers) as privileged participants" may be the imposed structure that makes the plan look more like the hybrid than like fully-autonomous self-organization; this could be argued more directly in the lit review.

4. **Semantic Consensus's 41–86.7% failure rates are conditional.** The figure is cited in the lit review's "human-at-boundary is the goal state, not day-one property" framing. But the conditionality on three orchestrator-centric multi-agent frameworks limits its transfer to the plan's artifact-centric substrate. The figure cannot do both jobs — it cannot simultaneously be a damning indictment of multi-agent systems *and* be conditional on a frame the plan doesn't use.

5. **Agora-Opt's "outcome-grounded debate protocol" has a solver oracle the plan lacks.** The lit review acknowledges this (the plan's domain has no equivalent oracle). The deeper question — whether decentralized intelligence-based reconciliation is robust without an oracle to ground it — is left as the plan's open empirical question. The lit review could state more directly that Agora-Opt's success is partly attributable to the oracle's grounding role, and the absence of an oracle in the plan's setting is the load-bearing risk.

6. **ScienceClaw + Infinite is closer to the plan than the lit review allows.** The "ArtifactReactor" component "autonomously discovers needs" — this is closer to artifact-side agency than the lit review's "passive provenance records" framing concedes. The narrowing of the plan's residual to "artifact as negotiating peer with explicit wants and task lifecycle" is honest; the current B§5 framing isn't.

---

**End of audit.**
