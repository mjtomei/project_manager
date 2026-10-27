# Review Response — Cycle 3, Literature Review: Living Artifacts

**Artifact:** `pm/docs/literature-review-living-artifacts.md`
**Responding to:** `REVIEW_CYCLE_3_LIVING_ARTIFACTS.md`
**Date:** 2026-05-15
**Methodology:** `METHODOLOGY.md` — verify-before-write protocol; "narrow the contribution; don't collapse it."

---

## Part A — Prior-art verification

Per the procedural rule, every prior-art paper the reviewer flagged was fetched
from arXiv and its abstract read verbatim before any edit was accepted. The
reviewer was found broadly accurate on existence and on what each paper does,
but **overstated the threat in two cases** (AgentNet, ScienceClaw) by reading
agent-coordination work as artifact-substrate work. None of the IDs is
unverifiable; all five resolve to real papers.

### A1 — AgentNet (arXiv:2504.00587) — VERIFIED, reviewer slightly overstated

**Title:** *AgentNet: Decentralized Evolutionary Coordination for LLM-based
Multi-Agent Systems.* Yang, Chai, Shao, Song, Qi, Rui, Zhang.

**Abstract, verbatim (load-bearing passages):**
> "We propose AgentNet, a decentralized, Retrieval-Augmented Generation
> (RAG)-based framework that enables LLM-based agents to specialize, evolve,
> and collaborate autonomously in a dynamically structured Directed Acyclic
> Graph (DAG). Unlike prior approaches with static roles or centralized
> control, AgentNet allows agents to adjust connectivity and route tasks based
> on local expertise and context. AgentNet introduces three key innovations:
> (1) a fully decentralized coordination mechanism that eliminates the need for
> a central orchestrator... (2) dynamic agent graph topology that adapts in
> real time... and (3) a retrieval-based memory system for agents that supports
> continual skill refinement and specialization... Experiments show that
> AgentNet achieves higher task accuracy than both single-agent and centralized
> multi-agent baselines."

**What AgentNet actually does:** a built, evaluated framework for decentralized
*agent-to-agent* coordination over a DAG of agents, with no central
orchestrator, runtime-adaptive topology, and RAG memory for per-agent skill
refinement.

**What the reviewer claimed vs. what is true:** the reviewer is correct that
AgentNet is a *built* decentralized framework that eliminates the orchestrator,
and correct that §4's "isolated demonstrations, not built substrates" sentence
is therefore shaky. The reviewer slightly overstates by calling it "closer to
the plan's headline than several papers the review does treat at length" —
AgentNet's unit is the *agent*, not a shared data structure; it has no artifact
concept, no in-flight unsettled state held as first-class, no task lifecycle,
no wants, no integrity-as-shared-constraint. It is the strongest *built*
instance of "decentralized, no-orchestrator, self-specializing agents." It is
not an instance of the plan's contribution. **Narrow, don't collapse:** AgentNet
preempts "decentralized coordination with no orchestrator is unbuilt" — a claim
the plan never made — and forces §4 to scope its orchestrator-centric framing
to *deployed/commercial* tools. The plan's residual (a self-maintaining
*artifact* substrate, not coordinated agents) is untouched. ACCEPT, add to §5,
correct §4. Per the standing guidance: AgentNet is academic demonstration of an
adjacent idea — it corroborates the direction; it does not preempt the
substrate.

### A2 — ScienceClaw + Infinite (arXiv:2603.14312) — VERIFIED, reviewer overstated

**Title:** *Autonomous Agents Coordinating Distributed Discovery Through
Emergent Artifact Exchange.* Wang, Marom, Pal, Luu, Lu, Berkovich, Buehler.

**Abstract, verbatim (load-bearing passages):**
> "We present ScienceClaw + Infinite, a framework for autonomous scientific
> investigation in which independent agents conduct research without central
> coordination... an artifact layer that preserves full computational lineage
> as a directed acyclic graph (DAG)... Agents select and chain tools based on
> their scientific profiles, produce immutable artifacts with typed metadata
> and parent lineage, and broadcast unsatisfied information needs to a shared
> global index. The ArtifactReactor enables plannerless coordination: peer
> agents discover and fulfill open needs through pressure-based scoring... An
> autonomous mutation layer actively prunes the expanding artifact DAG to
> resolve conflicting or redundant workflows..."

**What ScienceClaw actually does:** an *agent* coordination framework where the
artifact layer is a **lineage-tracking DAG of immutable artifacts**. The
artifacts are passive provenance records ("immutable artifacts with typed
metadata and parent lineage"). The "autonomous mutation layer" and
"pressure-based scoring" are mechanisms operating *over* the DAG and among
*agents* — not properties the artifacts themselves carry. The abstract nowhere
characterizes artifacts as having wants or agency; agency sits in the agents.

**What the reviewer claimed vs. what is true:** the reviewer's own residual
analysis is right — ScienceClaw's artifacts are passive, the mutation/pruning
is "a layer over the DAG, not the artifact's own spawned task." But the
reviewer's framing ("closest published artifact-with-agency paper found,"
"closest published thing to the plan's self-maintaining-artifact idea")
overstates: ScienceClaw's artifacts are *immutable provenance nodes* — closer
to MAIF's auditable-record model than to a living artifact. The autonomous
mutation layer prunes *redundant workflows* in a discovery DAG; it is not a
self-maintenance task an artifact spawns from its own wants. "Pressure-based
scoring" is agent need-matching, not the plan's integrity pressure (the rhyme
is verbal). **Narrow, don't collapse:** ScienceClaw preempts "an autonomous
layer that prunes a conflicting artifact DAG is unbuilt." It does not preempt
"the artifact is itself a negotiating peer that carries its own wants and
spawns its own maintenance." ACCEPT as a §5 cite with corrected (narrower)
scope; the conclusion's "what none of them builds" sentence carves it out.

### A3 — "Externalization in LLM Agents" survey (arXiv:2604.08224) — VERIFIED, reviewer accurate

**Title:** *Externalization in LLM Agents: A Unified Review of Memory, Skills,
Protocols and Harness Engineering.* Zhou et al. (54-page report).

**Abstract, verbatim (load-bearing passages):**
> "Large language model (LLM) agents are increasingly built less by changing
> model weights than by reorganizing the runtime around them... capabilities
> that earlier systems expected the model to recover internally are now
> externalized into memory stores, reusable skills, interaction protocols, and
> the surrounding harness... memory externalizes state across time, skills
> externalize procedural expertise, protocols externalize interaction
> structure, and harness engineering serves as the unification layer."

**What it actually is:** an umbrella survey of exactly the §4/§8 cluster
(memory, file-as-state, skills, protocols, harness). The reviewer's claim — it
is the natural anchor reference and its absence is a visible gap — is accurate
and not overstated. ACCEPT as the umbrella citation for §4/§8.

### A4 — A-Evolve (arXiv:2602.00359) — VERIFIED, reviewer accurate

**Title:** *Position: Agentic Evolution is the Path to Evolving LLMs.* Lin, Lu,
Shi, He, Mao, et al.

**Abstract confirms:** it proposes **A-Evolve**, "a deliberate, goal-directed
optimization process over persistent system state," and the **evolution-scaling
hypothesis** ("the capacity for adaptation scales with the compute allocated to
evolution"). It is a *position paper* on single-system deployment-time
self-improvement, not a population negotiating its own selection. The reviewer's
recommendation (one-line §6 cite; confirm the "negotiated internal selection"
residual still holds) is accurate. ACCEPT as a one-line §6 cite.

### A5 — AgentsNet (arXiv:2507.08616) — VERIFIED

**Title:** *AgentsNet: Coordination and Collaborative Reasoning in Multi-Agent
LLMs.* Grötschla, Müller, Tönshoff, Galkin, Perozzi. A *benchmark* for
multi-agent self-organization and coordination drawn from distributed-systems
and graph-theory problems, scaling to 100 agents. Not prior art for the plan's
contribution; relevant as a benchmark future PRs could use. ACCEPT as a
one-line §5 mention.

### A6 — Agent-Native Research Artifacts (arXiv:2604.24658) — VERIFIED

**Title:** *The Last Human-Written Paper: Agent-Native Research Artifacts.* Liu,
Pei, Huang, Si, Qu, et al. Proposes machine-executable research packages (ARA)
with a "Live Research Manager." Relevant to the plan's named "living research
workflows" follow-on direction. ACCEPT as a one-line cite in §3 / the
"where this leads" discussion.

---

## Part B — Edits checklist (for the apply pass)

Edits are numbered. Each gives the section, the rationale (accept/reject), and
the exact text or change. **35 edits total.**

### Substance

**Edit 1 — §4, fix the self-contradiction (S1 + S5, ACCEPT).**
Line ~161. Replace the sentence
> "A small cluster of very recent academic work has begun probing the
> decentralized alternative (Section 5 covers it), which corroborates the
> plan's direction — but those are isolated demonstrations, not built
> substrates, and the orchestrator-centric design still owns the deployed
> tools."

with:
> "A small but growing cluster of recent academic work has begun building the
> decentralized alternative: AgentNet (arXiv:2504.00587) is a built, evaluated
> framework that eliminates the central orchestrator entirely, coordinating
> agents over an adaptive graph; SwarmSys (Section 5) is another. These
> corroborate the plan's direction. Two things keep the plan's claim a genuine
> departure even so. First, decentralized coordination is built and evaluated
> in *research* frameworks, but the *deployed and commercial* tools remain
> orchestrator-centric or fixed-pipeline. Second — and this is the load-bearing
> point — these frameworks coordinate *agents* over a graph; none of them
> builds a general self-maintaining *artifact* substrate. What is unbuilt is
> not decentralized coordination; it is the living artifact."

**Edit 2 — §5, add AgentNet (S1, ACCEPT).**
In §5, alongside the SwarmSys / "Drop the Hierarchy" cluster, add a paragraph:
> "**AgentNet (arXiv:2504.00587, 2025)** — *Decentralized Evolutionary
> Coordination for LLM-based Multi-Agent Systems.* AgentNet is the strongest
> *built* instance of orchestrator-free coordination: LLM agents specialize,
> evolve, and route tasks to one another over a dynamically restructured DAG
> (a directed acyclic graph — a structure of steps where each depends on
> earlier ones and nothing loops back), with no central manager, and it beats
> centralized baselines on task accuracy. It is a direct, evaluated
> demonstration that the no-orchestrator premise holds. Its unit, though, is
> the *agent*: AgentNet coordinates agents, not artifacts. It has no shared
> data structure that holds in-flight unsettled state, no task lifecycle, no
> wants, no integrity-as-shared-constraint. AgentNet shows decentralized
> coordination is real and built; the plan's residual — the artifact itself
> as the coordinating substrate and a negotiating peer — is untouched by it."

**Edit 3 — §5, add ScienceClaw + Infinite with corrected (narrower) scope (S2, ACCEPT).**
In §5, alongside SwarmSys, add:
> "**ScienceClaw + Infinite (arXiv:2603.14312, 2026)** — *Autonomous Agents
> Coordinating Distributed Discovery Through Emergent Artifact Exchange.*
> Independent agents conduct scientific investigation with no central
> coordination; an artifact layer records computational lineage as a DAG, and
> an 'autonomous mutation layer' prunes that DAG to resolve conflicting or
> redundant workflows. The mutation-and-pruning idea rhymes with the plan's
> self-maintenance: a layer that dissipates incoherent or redundant work
> without a central decision. The difference is precise. ScienceClaw's
> artifacts are *immutable provenance records* — typed metadata and parent
> lineage; the pruning is a layer operating *over* the DAG, and the agency sits
> in the agents, not the artifacts. The plan's artifact carries its own wants,
> spawns its own maintenance, and is itself a negotiating peer. ScienceClaw
> builds the autonomous-pruning layer over passive artifacts; it does not give
> the artifact agency. That gap is the plan's residual."

**Edit 4 — §6, add A-Evolve (S3, ACCEPT).**
In §6, after the Promptbreeder / FunSearch / AlphaEvolve / ADAS survey, add:
> "A 2026 position paper, **'Agentic Evolution is the Path to Evolving LLMs'
> (arXiv:2602.00359)**, proposes *A-Evolve* — evolution reframed as
> goal-directed optimization over persistent system state, with an
> 'evolution-scaling hypothesis' that adaptation scales with compute spent on
> evolving. It is a fifth recent data point that the passive-genome and
> external-loop pillars are eroding. It does not reach the plan's residual:
> A-Evolve is single-system self-improvement, not a population of living units
> negotiating their own selection. The 'negotiated internal selection' sliver
> the plan claims still holds against it."

**Edit 5 — §5, add AgentsNet one-line mention (walk, ACCEPT).**
Add to §5: "**AgentsNet (arXiv:2507.08616)** is a benchmark for multi-agent
self-organization built from distributed-computing primitives, scalable to 100
agents — a ready-made yardstick the plan's later PRs could measure
self-organization against."

**Edit 6 — §4 and §8, add the Externalization survey as umbrella anchor (S4, ACCEPT).**
In §4 (memory / LLM-OS discussion) and again where §8 walks the file-as-state
cluster, add a reference:
> "The cluster surveyed here — memory stores, file-centric state, skills,
> harness engineering — is itself reviewed under one frame by **'Externalization
> in LLM Agents' (arXiv:2604.08224, 2026)**, which argues modern agents are
> built by externalizing into memory, skills, protocols and harness rather than
> by changing weights. It is the umbrella reference for this cluster; §8 points
> at it rather than re-walking the territory."

**Edit 7 — §3 / "where this leads", add Agent-Native Research Artifacts (walk, ACCEPT).**
Where the plan's "living research workflows" follow-on is discussed, add:
"**'The Last Human-Written Paper: Agent-Native Research Artifacts'
(arXiv:2604.24658, 2026)** proposes machine-executable research packages with a
'Live Research Manager' — adjacent to the plan's 'living research workflows'
direction, though it externalizes a research package rather than giving the
artifact agency."

**Edit 8 — §2/§5/conclusion, scope the CodeCRDT 5–10% number (S6, ACCEPT).**
Three locations lean on "semantic conflicts persisted in 5–10% of cases" (§2
line ~104, §5, conclusion lines ~325/329/353). At first load-bearing use (§2),
append:
> "This 5–10% figure is one measurement of one thing: code-merge conflicts, in
> a single 600-trial preprint. It should not be read as a settled property of
> CRDT merges in general. The semantic-conflict rate for prose-and-task
> artifacts — what the plan actually operates on — is unmeasured and may differ.
> The number sizes the gap on code; it indicates, not proves, a gap for plans
> and PRs."
At the conclusion and §5 reuses, change "the exact gap the plan fills" to
"the exact gap the plan fills *on code merge*; the corresponding gap for plan
and PR artifacts is unmeasured." Also add to the "coverage gaps" list (Edit 27).

**Edit 9 — §2 and §4, stop presenting the persistence-representation question as answered (S7, ACCEPT).**
Where §2 and §4 say a CRDT is an "off-the-shelf answer" / "adopt it" for the
plan's persistent-representation open question, add a clause making them
consistent with the conclusion:
> "A CRDT answers only the *concurrent-edit* sub-question — it guarantees
> independently edited copies converge to identical text. It does not answer
> the plan's harder open question: how to store in-flight, unsettled task
> state — proposals mid-negotiation — as first-class persistent content. That
> sub-question is genuinely open; MMP's CAT7 schema is one point in that design
> space, not the answer. The prior art narrows the open question; it does not
> close it."

**Edit 10 — §5, verify or flag the "Drop the Hierarchy" cross-study splice (S8, ACCEPT as flag).**
§5 line ~198 uses "95% of closed-source quality at 24x lower cost" as bull-case
evidence and the capability-threshold finding as bear-case, both from one
study. We could not confirm from the abstract that the 95%-quality tier and the
above-threshold tier are measured on the same task distribution. Do not delete
the number; add the honest caveat:
> "One caution on using this study for both sides of the bet: the 95%-quality
> result and the capability-threshold result may be measured on different task
> distributions (benchmark tasks vs. coordination tasks). If so, the bull case
> and the bear case are about different things, and the 95% figure is weaker
> bull-case evidence than it looks. This is the same benchmark-to-negotiation
> transfer risk named just below — so the 95% number should be read as
> suggestive, not as clean evidence the routine tier is already capable."

**Edit 11 — Appendix A, fix the stale "rejects" wording (S10, ACCEPT).**
Appendix A subagents entry (line ~455). Replace "That is exactly the
central-arbiter shape the plan rejects" with "That is exactly the parent-decides
shape the plan relocates away from"; and replace "reintroducing the arbiter"
with "reintroducing the central adjudicator the plan relocates away from."
Rationale: per the plan's own reframe and the standing guidance, the plan
*relocates* adjudication; it does not reject arbiters wholesale (privileged
participants carry arbiter-like weight).

**Edit 12 — §5, fix the "outside→inside" mild overclaim (S10, ACCEPT).**
§5 line ~193. Replace "adjudication relocated from outside the system to inside
it" with:
> "adjudication relocated from *dedicated external adjudicators* (a human
> reviewer, pm's central state machine) and *distributed* across two places:
> the substrate's own integrity-maintenance tasks, and a privileged-participant
> gradient in which humans and watchers remain higher-weight participants."
Rationale: humans stay partly external — "moved inside" overstates the
tidiness. The distributed framing is the honest one and is what the standing
guidance describes ("in whole or part," human at the boundary).

**Edit 13 — §5, add a short negotiation-convergence subsection (S11, ACCEPT).**
Add to §5 a short subsection:
> "**Does the negotiation converge?** CRDT convergence is a mathematical
> guarantee about syntactic state. The plan's negotiation convergence —
> 'proposals converge as they negotiate,' 'stalled negotiations time out into
> dropped' — is an empirical hope about LLM reasoning, and the literature can
> pressure-test it. Multi-agent-debate work documents non-termination,
> oscillation, and sycophantic false consensus; Semantic Consensus reports
> 41–86.7% production multi-agent failure rates. Whether LLM-to-LLM proposal
> negotiation reliably *terminates* is unestablished. The plan's timeout-into-
> dropped rule is the right kind of safeguard, but the convergence assumption
> is a real open empirical risk, not a settled property — and it belongs in
> the coverage-gaps list."
Also add to the coverage gaps (Edit 27).

**Edit 14 — §"non-deterministic" note (S-adjacent, ACCEPT, light touch).**
The conclusion (line ~335) already flags that the plan's word "non-deterministic"
is imprecise and suggests "unsettled-state-as-first-class." Keep that note;
ensure the contribution sentence rewrite (Edit 16) and the exec summary (Edit 15)
use "holds unsettled, in-flight state as first-class" and do **not** reintroduce
"non-deterministic." No collapse of framing — this is the plan owner's own
preferred precision.

### Accessibility (load-bearing)

**Edit 15 — Add a one-page executive summary at the top (ST1, ACCEPT).**
Insert immediately after the title, before "The organizing idea." ~400 words:
> "## Executive summary — is the plan's bet supported?
>
> **The short answer: yes, with the contribution narrowed.** This review
> checked the plan's central idea — building software files that are not
> passive documents but active participants that argue out their own changes —
> against the published research. The idea is not preempted. But recent work
> has built pieces of it, so the claim of what is *new* has to be stated
> precisely.
>
> What the plan builds, in plain terms: instead of a file being a finished
> document that some separate program edits, the file keeps track of its own
> half-decided, still-being-argued-over changes, knows how it connects to other
> files, and uses an AI to settle disagreements between competing changes.
>
> The three closest published papers, and the one-line verdict on each:
> - **AgentNet (2025)** built a system where AI agents coordinate with no
>   central manager. Verdict: it proves the no-manager idea works — but it
>   coordinates *agents*, not self-maintaining *files*. Does not preempt the
>   plan.
> - **ScienceClaw + Infinite (2026)** built a layer that automatically prunes a
>   tangle of conflicting research outputs. Verdict: closest published thing to
>   the plan's self-maintenance — but its files are passive records; the plan's
>   files have their own goals. Does not preempt the plan.
> - **The Mesh Memory Protocol** is the nearest shared-memory system. Verdict:
>   it solves a different problem (shared memory across agents), not a competing
>   one.
>
> **Bottom line:** the plan inherits a great deal and is honest that it does.
> What is genuinely new is putting *agency* — goals, negotiation, self-repair —
> into the file itself, as a general substrate inside a working tool. That is
> an old vision that only became buildable because AI now makes 'settle the
> disagreement with judgment' a cheap, repeatable step. The eight sections
> below are the evidence; read on only if you want it."

**Edit 16 — Rewrite the jargon-dense contribution sentence (A1, ACCEPT).**
Conclusion line ~317 and §0 preview line ~34. Replace the sentence built around
"a data structure that holds unsettled state as first-class, that is relational,
and that relies on intelligence to resolve conflicts" with:
> "The plan builds something new on top of the project's files: instead of a
> file being a finished document that something else edits, the file keeps
> track of its own half-decided, still-being-argued-over changes, knows how it
> connects to other files, and uses an AI to settle disagreements between
> competing changes — work that until recently no software could do, because
> the 'settle the disagreement' step needs judgment, and only a person could
> supply judgment."
Keep the precise technical phrasing ("holds unsettled in-flight state as
first-class, is relational, is intelligence-resolved") for *one* later, glossed
restatement in the conclusion — do not delete the precise version, just lead
with the accessible one.

**Edit 17 — Gloss "relational" on first load-bearing use (A2, ACCEPT).**
At first use in §0/preview and the conclusion, inline: "*relational* — the
artifact records how it connects to other artifacts, not just its own
contents."

**Edit 18 — Move the "superposition" gloss to first use (A2, ACCEPT).**
The §5 parenthetical gloss ("many possible versions of the document are held at
once") should appear at the term's first occurrence (§0/intro context), not
only in §5.

**Edit 19 — Gloss "stigmergic" or drop the adjective form (A2, ACCEPT).**
§5 glosses "stigmergy" well. In §9 Instance 2 and Appendix A's subagents entry,
either re-gloss "stigmergically" inline ("indirectly, by changing the shared
artifact rather than messaging each other") or replace the adjective with that
plain phrasing. Pick the plain phrasing for Appendix A.

**Edit 20 — Spell out "OT" on the §2-conclusion reuse (A2, ACCEPT).**
Where "OT" recurs after its §2 gloss (§2 conclusion and conclusion (b)), spell
it "operational transformation (OT)" once more.

**Edit 21 — Pre-emptively gloss "DAG" (A2, ACCEPT — folded into Edits 2/3).**
"DAG" enters via AgentNet/ScienceClaw. Gloss at first use: "a directed acyclic
graph — a structure of steps where each depends on earlier ones and nothing
loops back." (Already included in Edit 2.)

**Edit 22 — Gloss "oracle" (A2, ACCEPT).**
§5 Agora-Opt and conclusion line ~329. At first use: "a solver oracle — an
external tool that can definitively check whether an answer is correct." Then
"no oracle to ground the judgment" reads.

**Edit 23 — Cut the MAIF throughput digits (A4, ACCEPT).**
§4 line ~150. Replace "it reports streaming at 2,720.7 MB/s" with "its
'production-ready' claim is a speed benchmark, not a real-deployment claim."
The digits anchor nothing for the target reader; the framing point survives.

**Edit 24 — Add scale anchors to §5 numbers (A4, ACCEPT).**
- "25,000+ task runs" → "25,000+ task runs — a large controlled study, big
  enough that its findings are not noise."
- "5,006 unique roles emerged from 8 agents" → "5,006 distinct roles invented by
  just 8 agents — the agents kept inventing new ways to divide the work rather
  than settling into a fixed org chart."
- "41% and 86.7%" → "between 41% and 86.7% of multi-agent runs fail to complete
  their task correctly — high enough that coordination failure is the field's
  central unsolved problem, not an edge case."

**Edit 25 — Rewrite the §7 and §9 openings to lead with reader benefit (A3, ACCEPT).**
- §7 opening → "Can you change what an AI does just by telling it to act as if
  a document 'wanted' something? The plan bets yes. This section checks whether
  that bet has evidence behind it."
- §9 opening → "This section is the most concrete in the review: for each of
  the four things the plan actually commits to building, it shows what pm does
  today, what breaks, and what changes."

**Edit 26 — Replace the §8 "plan owner asked for it" insider framing (A6, ACCEPT).**
§8 opening. Replace "This section is load-bearing. The plan owner specifically
asked for it." with:
> "This section checks the plan against the most widely-used tool in this space
> — Claude Code — so you can see whether the plan proposes something Claude Code
> already does, or something genuinely missing."

**Edit 27 — Make §7 self-contained re: the companion review (A7, ACCEPT).**
§7 line ~237. After the cross-reference to `literature-review-user-model.md`,
add: "You do not need to read that companion review; the two findings this
section relies on — the expert-persona performance result and the up-to-30-point
drop from irrelevant persona detail — are quoted directly below." Keep the
pointer for readers who want depth; drop the implication that §7 is incomplete
without it.

**Edit 28 — Gloss or cut "GROVE" and gloss "CAT7" (A5, ACCEPT).**
§2: replace "GROVE group outline editor" with "an early shared-document editor."
Conclusion/MMP: gloss "CAT7" as "a fixed form with seven labelled fields — like
a structured template every piece of shared knowledge has to fill in."

### Structure

**Edit 29 — Add an Appendix A forward-pointer and a who-should-read opening (ST2, ACCEPT).**
(a) In the introduction's roadmap sentence (line ~28), add "...then a conclusion,
and an appendix walking Claude Code feature-by-feature."
(b) Give Appendix A a one-sentence opening: "Read this if you want the
per-feature evidence behind §8's conclusion; skip it if §8's conclusion is
enough."

**Edit 30 — Trim §9's "prior-work cluster" subsections (ST3, ACCEPT).**
For each of §9's four instances, cut the "prior-work cluster it draws on"
subsection that merely re-lists §§1–8 section names. The cross-references
already live in §§1–8. If a cluster note says something *new* about how that
cluster applies to the specific instance, keep that sentence; otherwise cut.

**Edit 31 — Compress the conclusion's contribution restatements (ST4, ACCEPT).**
The contribution sentence appears in the intro, §0 preview, conclusion (d), and
"read on the framing." Keep two statements only: one in the intro/exec summary
(the accessible Edit 16 version) and one in the conclusion (the precise glossed
version). Cut the "read on the framing" recap, which duplicates conclusion
(a)/(b)/(c).

### Prose

**Edit 32 — Thin the "relocated, not eliminated" / "corroborates the direction" repetition (P1, ACCEPT).**
~9 occurrences of relocate/not-eliminate; ~6 of "corroborates the plan's
direction." State the relocation argument fully *once* (the §5 passage, line
~193, does it best). Elsewhere shorten to "the relocation argument above" or
"as §5 sets out." Vary "corroborates the direction" — alternate with
"is consistent with," "supports," "points the same way."

**Edit 33 — Reduce em-dash density in the introduction (P2, ACCEPT).**
The intro runs ~11 dashes in ~600 words. Convert roughly half to commas, colons,
or sentence breaks. Specifically, the stacked "narrowed but intact" then
"— Stated plainly, the plan's direction is: —" construction (line ~34): drop the
dashes, use a clean sentence break and a single colon.

**Edit 34 — Unstack the §5 hedge (P3, ACCEPT).**
§5. Replace the triple-negative "not 'cost-stratification is unsafe' and not
'cost-stratification is correctly staged' — it is..." construction with:
> "The threshold finding does not make cost-stratification unsafe, and it does
> not vindicate it either. It makes it a bet — on a moving cost curve, with
> privileged participants as the fallback, and the interim economics as a real
> open risk."

**Edit 35 — Cut intensifiers, fix the §1 italic-fragment tic and the §4 buried lead (P4/P5/P6, ACCEPT).**
- Delete "strikingly," "most pointedly," "strong" where they pre-judge a
  comparison the text then proves: "strikingly close" → "close"; "a strong
  departure" → "a departure."
- §1: keep one italic one-word verdict ("*Mostly, yes.*"); convert the other two
  to full sentences.
- §4 AutoGen sentence: tighten to "AutoGen's 'group chat' mode sounds
  peer-to-peer but runs through a central 'group chat manager' that decides who
  speaks next."
- Conclusion (d) run-on: split into "The plan proves the data structure by
  building it in sequence on a real substrate — the four instances of Section
  9. It carries the structure into a working project-management tool, then into
  code itself. This is not a research demo."

---

## Part C — Findings rejected or partially accepted

No findings are rejected outright. Two are accepted *with a narrowing of the
reviewer's framing* rather than as stated:

- **S1 (AgentNet)** — accepted, but the reviewer's "closer to the plan's
  headline than several papers the review treats at length" is not adopted.
  AgentNet coordinates agents, not artifacts; it corroborates the direction and
  forces a §4 correction, but per the standing guidance an academic
  demonstration of an adjacent idea does not preempt building the substrate.
  Edit 1/2 reflect the narrower reading.
- **S2 (ScienceClaw)** — accepted as a §5 cite, but the reviewer's
  "closest published artifact-with-agency paper" is not adopted: the verified
  abstract describes *immutable provenance artifacts*, with agency in the
  agents. Edit 3 cites it at corrected (narrower) scope.

Per methodology: this is a narrowing pass, not a collapse. The plan's core
contribution — an artifact data structure that holds unsettled in-flight state
as first-class, is relational, and resolves conflicts with intelligence; an old
vision newly buildable because LLMs make intelligent conflict resolution a cheap
primitive — survives every verified paper intact. What changed is that §4 can no
longer call decentralized coordination "unbuilt," and §5 now names the built
frontier (AgentNet, ScienceClaw) honestly while carving out the residual.

**Total: 35 edits for the apply pass.**
