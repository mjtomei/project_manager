# Review Cycle 3 — Literature Review: Living Artifacts

**Artifact:** `pm/docs/literature-review-living-artifacts.md` (~14,267 words)
**Reviewer:** fresh adversarial pass, blind to prior cycles at drafting time
**Date:** 2026-05-15
**Methodology:** four blocks (substance / structure / accessibility / prose), step-5 citation-graph walk both directions, "narrow the contribution; don't collapse it"

---

## Headline assessment

This is a strong, careful document. It is far better than most literature
reviews this loop has seen: the contribution is already narrowed (not
collapsed), the prior-art comparisons are mostly point-by-point, and the
"corrected scope" treatment of recent close work is honest. The prior cycle's
rewrites largely hold up under verification.

But it is not done. The citation-graph walk found **three genuinely close
2025–2026 papers the review does not cite**, at least one of which
(AgentNet) preempts a contribution the review still presents as the plan's
own. The accessibility block (load-bearing) surfaces real failures: the
review is *long*, several sections still open with a paper citation rather
than a reader benefit, and the "narrowed contribution sentence" the whole
document builds toward is itself jargon-dense. And the "relocated, not
eliminated" reframe — while honest in intent — has hardened into a
load-bearing phrase repeated so many times it now reads as a tic, and in one
place it overclaims.

**Findings: 27 total — 11 substantive, 16 phrasing/accessibility/structure.**

A cycle-3 pass under this methodology should be the hardest. This one is
harder than a convergence signal would predict, because the citation walk
was productive. That is the signal: the work is good but the frontier moved.

---

# Block 1 — Substance

## S1 (SUBSTANTIVE) — AgentNet is uncited and it preempts a live contribution claim

The citation walk's most damaging find. **AgentNet: Decentralized
Evolutionary Coordination for LLM-based Multi-Agent Systems**
(arXiv:2504.00587, April 2025) is not in the references. It predates the
review's earlier drafts by over a year. It is closer to the plan's headline
than several papers the review *does* treat at length.

Verbatim from the abstract:

> "We propose AgentNet, a decentralized, Retrieval-Augmented Generation
> (RAG)-based framework that enables LLM-based agents to specialize, evolve,
> and collaborate autonomously in a dynamically structured Directed Acyclic
> Graph (DAG). Unlike prior approaches with static roles or centralized
> control, AgentNet allows agents to adjust connectivity and route tasks
> based on local expertise and context. AgentNet introduces three key
> innovations: (1) a fully decentralized coordination mechanism that
> eliminates the need for a central orchestrator... (2) dynamic agent graph
> topology that adapts in real time to task demands... and (3) a
> retrieval-based memory system for agents that supports continual skill
> refinement and specialization."

**What AgentNet actually does:** fully decentralized coordination with *no
central orchestrator* (the review's §4 says decentralized work is "isolated
demonstrations" — AgentNet is a built framework, evaluated, not a study);
dynamic topology that adapts at runtime; agents that *specialize and evolve*
their own capability. It is the strongest published instance of
"decentralized coordination, no orchestrator, agents that grow" — exactly
the cluster §4 and §5 survey.

**What the plan does that AgentNet does not:** AgentNet has no artifact
concept — coordination is agent-to-agent over a DAG, not over a shared
self-maintaining data structure; no task lifecycle whose phases are
trajectories; no "wants"; no integrity-as-shared-constraint; the unit is the
agent, not the artifact. The residual survives. But the review's §4 sentence
"those are isolated demonstrations, not built substrates, and the
orchestrator-centric design still owns the deployed tools" is now **factually
shaky** — AgentNet is a built, evaluated decentralized framework that
eliminates the orchestrator. The review should:

1. Add AgentNet to §4 or §5 as the closest *built* decentralized-coordination
   framework.
2. Rewrite the §4 sentence: not "isolated demonstrations" but "a small but
   growing cluster of *built* decentralized frameworks (AgentNet, SwarmSys)
   now eliminate the orchestrator — but coordinate agents over a graph, not a
   self-maintaining artifact."
3. Spend the residual: AgentNet preempts "decentralized, no-orchestrator,
   self-evolving agents" as a *novelty*. The plan never claimed that as the
   novelty — but §4's framing leans on the dominant design being
   orchestrator-centric, and AgentNet weakens "the orchestrator-centric design
   still owns the field." Narrow it to "owns the *deployed/commercial* tools";
   the *research* frontier has decentralized built systems.

This is the single finding the response cycle most needs to handle properly.

## S2 (SUBSTANTIVE) — ScienceClaw+Infinite is uncited and is the closest artifact-with-agency paper found

**"Autonomous Agents Coordinating Distributed Discovery Through Emergent
Artifact Exchange"** (ScienceClaw + Infinite, arXiv:2603.14312, March 2026).
Not cited. From the abstract and body:

> "We present ScienceClaw + Infinite, a framework for autonomous scientific
> investigation in which independent agents conduct research without central
> coordination."

It has an **artifact layer** tracking lineage as a DAG; **"pressure-based
scoring"** for peer discovery; an **"ArtifactReactor"** enabling
**"plannerless coordination"**; and — most pointed — an **"autonomous
mutation layer"** that **"actively prunes the expanding artifact DAG to
resolve conflicting or redundant workflows."**

That autonomous-mutation-layer-that-prunes-conflicting-workflows is
structurally the plan's *self-maintenance task that dissipates incoherent
proposals* (the plan's "dropped" trajectory and integrity-pressure
mechanism). And "pressure-based scoring" rhymes hard with the plan's
"integrity pressure." This is the closest published thing to the plan's
self-maintaining-artifact idea the walk found.

**Residual after honest comparison:** ScienceClaw's artifacts are
characterized in the abstract review as "semi-active... they don't possess
independent wants; rather, they facilitate agent coordination through
structured metadata and provenance." So the artifact still isn't an agent
with wants — the mutation/pruning is a *layer over* the DAG, not the
artifact's own spawned task. The plan's residual (artifact carries its own
wants, spawns its own maintenance, is itself a negotiating peer) survives.
But the review can no longer imply that "an artifact layer with autonomous
conflict-pruning and no central coordinator" is unbuilt. It should be cited
in §5 alongside SwarmSys, and the conclusion's "what none of them builds"
sentence should explicitly carve ScienceClaw out: it builds the
autonomous-pruning layer; it does not give the artifact wants.

## S3 (SUBSTANTIVE) — The "Agentic Evolution / A-Evolve" position paper undercuts §6's framing

**"Position: Agentic Evolution is the Path to Evolving LLMs"**
(arXiv:2602.00359, Feb 2026) proposes **A-Evolve**, "a framework treating
real-world improvement as deliberate, goal-directed optimization over
persistent system state," with an "evolution-scaling hypothesis." This is
directly in §6's territory ("evolutionary computation reframed") and in §4's
("persistent state drives behavior"). §6 currently surveys Promptbreeder /
FunSearch / AlphaEvolve / ADAS and concludes the only unclaimed sliver is
"negotiated internal selection." A-Evolve adds a *fifth* recent data point
that the genome-as-passive-string and external-loop pillars are eroding, and
it explicitly frames evolution as optimization over *persistent state* —
which the review elsewhere treats as the plan's territory (§4, §8). At
minimum cite it in §6 and confirm the "negotiated internal selection"
residual still holds against it (it does — A-Evolve is single-system
self-improvement, not a population negotiating its own selection — but the
review must say so rather than leave the gap).

## S4 (SUBSTANTIVE) — "Externalization in LLM Agents" survey is the natural §4/§8 anchor and is missing

**"Externalization in LLM Agents: A Unified Review of Memory, Skills,
Protocols and Harness Engineering"** (arXiv:2604.08224, April 2026) is a
unified review covering exactly the cluster §4 (memory, LLM-OS) and §8
(file-as-state) survey — MemGPT, InfiAgent, file-centric state, skills,
harness engineering all sit inside its scope. A literature review that
surveys this space and omits the *survey of this space* has a visible gap. A
reader checking whether §4/§8 are complete will find this and wonder what
else was missed. Cite it as the umbrella reference for the externalization
cluster; it also lets §8 shorten its own walk by pointing at it.

## S5 (SUBSTANTIVE) — §4 overclaims that decentralized work is "isolated demonstrations, not built substrates"

Independent of S1, the §4 sentence — "those are isolated demonstrations, not
built substrates, and the orchestrator-centric design still owns the
deployed tools" — is now contradicted by the review's *own* §5, which
describes SwarmSys as "a closed-loop framework." A closed-loop framework is a
built substrate. AgentNet (S1) is another. The review wants it both ways:
§5 treats SwarmSys as a real coordination architecture, §4 dismisses the
decentralized cluster as "isolated demonstrations." Pick one. The accurate
statement is: "decentralized coordination is built and evaluated in research
frameworks (SwarmSys, AgentNet); what is not built is the *general
self-maintaining artifact substrate* — those frameworks coordinate agents,
not artifacts." That sentence is both true and still leaves the plan's
contribution intact. The current sentence is false and the contribution
survives without it.

## S6 (SUBSTANTIVE) — The CodeCRDT "5–10% semantic residual" is load-bearing and single-sourced

§2, §5, and the conclusion (b) all lean on CodeCRDT's finding that "semantic
conflicts persisted in 5–10% of cases." This number does heavy work — it is
"the exact gap the plan fills." But it comes from one preprint
(arXiv:2510.18893), on one task type (code merge), in a 600-trial study, and
the review itself flags CodeCRDT's authorship vaguely ("'CodeCRDT' authors").
A single preprint's single number should not be the empirical keystone of a
contribution argument. Two fixes: (a) state explicitly that 5–10% is
*code-merge-specific* and may not transfer to plan/PR artifacts — the
semantic-conflict rate for prose-and-task artifacts is unmeasured; (b) add
this to the "coverage gaps" list. As written, the conclusion treats 5–10% as
if it were a settled property of CRDT merges in general. It is one
measurement of one thing.

## S7 (SUBSTANTIVE) — The plan's actual schema/representation question gets surveyed but never answered

§2 and §4 repeatedly say the plan's open question ("What is the artifact's
persistent representation? CRDT-friendly?") has an "off-the-shelf answer" —
"model the artifact as a CRDT," "adopt it." But §5's Agora-Opt discussion and
the MMP comparison both show the hard part is *semantic*, not syntactic, and
a CRDT gives only syntactic convergence. So the review tells the plan "adopt
a CRDT" while also telling it the CRDT solves the easy 90–95% and the plan's
whole job is the residual. That is not contradictory but it *reads* as the
review answering the plan's open question when it has not. The review should
say plainly: the persistence-representation open question is **not** answered
by the prior art — CRDTs answer the *concurrent-edit* sub-question, the
*how-do-you-store-in-flight-unsettled-task-state* sub-question is genuinely
open, and MMP's CAT7 schema is one point in that space, not the answer. The
conclusion's MMP paragraph half-says this ("the plan's open questions ...
remain open") — but §2 and §4 undercut it. Make §2/§4 consistent with the
conclusion.

## S8 (SUBSTANTIVE) — The cost-stratification "bet" treatment is good but rests on a cross-study number splice

§5's cost-stratification analysis is the review's best passage — genuinely
rigorous. But one move is shaky: it cites "open-source models reaching 95% of
closed-source quality at 24x lower cost" as evidence *for* the bet, drawn
from "the same study" ("Drop the Hierarchy"). It then uses the threshold
finding *against* the bet, from the same study. Using one study's two
findings as both the bull and bear case is fine *only if* the 95%/24x number
and the capability-threshold number are measured on the same task
distribution — otherwise the review is splicing. The review should confirm
(or flag) that the 95%-quality models are the *same tier* as the
above-threshold models. If "Drop the Hierarchy" measured 95%-quality on
benchmark tasks but the threshold on coordination tasks, the bull case and
bear case are about different things and the splice is unsound. This is
exactly the "benchmark-to-negotiation transfer" risk the review names — so
the review already half-knows; it should not then use the 95% number as
clean bull-case evidence.

## S9 (SUBSTANTIVE) — Verification of the five corrected-scope citations

Per the task, spot-checking against abstracts:

- **Salemi et al. (2510.01285)** — VERIFIED. Abstract confirms "a central
  agent posts requests to a shared blackboard" and "autonomous subordinate
  agents... volunteer to respond based on their capabilities." The review's
  §1 characterization ("retains a central agent that posts requests... what
  that paper removes is narrower — the requirement that a central coordinator
  know each agent's capabilities") is **accurate**. Good correction; not
  over- or under-stated.
- **Han & Zhang (2507.01701)** — VERIFIED. Abstract confirms "agents that
  will take actions are selected based on the current content of the
  blackboard, and the selection and execution round is repeated until a
  consensus is reached." The review's claim ("Han & Zhang's selection step is
  itself consistent with a control component reading the board") is
  **accurate** — the selection step is a control component by another name.
  The "board remains passive" claim is also accurate. Good.
- **InfiAgent / "Everything is Context"** — characterizations
  ("passive externalized memory" / "human-curated context infrastructure")
  are consistent with the abstracts surfaced in the walk and with the
  "Externalization" survey's description of InfiAgent's file-centric state.
  Not independently full-text verified, but the corrected scope reads
  accurate, not over-corrected.
- **Agora-Opt (2604.25847)** — the review's characterization (outcome-grounded
  decentralized reconciliation, solver oracle, agent-centric not
  artifact-centric) matches the description. Accurate.

**Verdict on the five corrected-scope citations:** all five check out. The
prior cycle did *not* over- or under-correct. This is a positive convergence
signal — the one place cycle 3 was told to look hardest, the work holds.

## S10 (SUBSTANTIVE) — The "no central arbiter" reframe: mostly consistent, one stale survivor, one mild overclaim

The task asked specifically whether a stale absolute-"no arbiter" claim
survives. Checking intro / §4 / §5 / §9 / conclusion:

- Intro §claim 2, §4, §5, §9-Instance-3, conclusion (d): all use the
  "relocated, not eliminated" framing consistently. Good — the reframe held.
- **One stale survivor:** the plan-section header in the *plan itself* is
  "No central arbiter" — but the review is reviewing the lit review, not the
  plan, so that is out of scope. Within the lit review, the closest to a
  stale absolute is Appendix A's subagents entry: "That is exactly the
  central-arbiter shape the plan rejects" and "reintroducing the arbiter."
  "The plan rejects the central-arbiter shape" is, by the review's own
  reframe, imprecise — the plan *relocates* adjudication, it does not reject
  arbiters wholesale (privileged participants carry arbiter-like weight).
  Appendix A should say "the parent-decides shape the plan relocates away
  from" not "rejects." Minor but it is the one inconsistency.
- **Mild overclaim in the reframe itself:** "relocated, not eliminated" is
  repeated ~9 times and in §5 becomes "adjudication relocated from outside
  the system to inside it." But the plan's privileged-participant gradient
  *keeps humans and watchers as higher-weight participants* — i.e. some
  adjudication stays partly external (a human is not "inside the substrate").
  The honest phrasing is "relocated from *dedicated external adjudicators*
  into the substrate's integrity tasks *and* a privileged-participant
  gradient" — adjudication is distributed across substrate tasks AND
  privileged participants, not cleanly "moved inside." The review's §5
  parenthetical ("Whether... 'in' or 'above'... is an implementation detail")
  gestures at this but the repeated clean "outside→inside" phrasing
  overstates the tidiness. Pick the distributed framing and stop saying
  "inside."

## S11 (SUBSTANTIVE) — Missing: no engagement with whether negotiation *converges*

The plan and review both lean on "proposals converge as they negotiate." The
review surveys coordination, conflict-resolution, CRDT convergence — but
CRDT convergence is a *mathematical guarantee* about syntactic state, whereas
the plan's negotiation convergence is an *empirical hope* about LLM
reasoning. Nowhere does the review ask: what is the evidence that LLM-to-LLM
proposal negotiation *terminates*? "Drop the Hierarchy" and the
multi-agent-debate literature have data on non-termination, oscillation, and
sycophantic false consensus. Semantic Consensus's cited "41–86.7% production
failure rates" hint at it. The review should add a short subsection (in §5)
on negotiation *termination/convergence* as an open empirical risk — the
plan's "converging as they negotiate" and "stalled negotiations time out
into dropped" are assertions the literature can pressure-test, and the review
currently does not bring that pressure.

---

# Block 2 — Structure

## ST1 (STRUCTURE) — The review is too long for its stated audience

~14,267 words. The stated audience is "a non-developer evaluating whether the
plan's bet is supported by prior work." That reader will not finish 14,000
words. The methodology's Block 3 says explicitly: "They will not read three
sections to understand the first one." Eight survey sections + §9 +
multi-part conclusion + appendix is a *reference document*, not an
evaluation aid. Recommendation: add a one-page **executive summary** at the
top — "Is the bet supported? Short answer, with the three closest papers and
the one-line verdict on each" — so the target reader gets the answer in 400
words and the 14,000 words become the backup. Without this, Block 3's
audience is served by the glossary sentences but defeated by the length.

## ST2 (STRUCTURE) — §8 → Appendix A move: helps the body, but the appendix is under-referenced

The task asked specifically. Moving the Claude Code feature-by-feature walk
to Appendix A **helps** — §8 is now a tight conclusion-plus-evidence section
instead of a nine-bullet slog, and the body flows better into §9. Good
structural call. But: Appendix A is referenced from the body exactly *once*
("the full walk is in Appendix A"), buried mid-paragraph in §8. A reader
skimming section headers will not know the appendix exists or why they would
want it. Fixes: (a) add a forward-pointer in the introduction's roadmap
sentence ("...then a conclusion, and an appendix walking Claude Code
feature-by-feature"); (b) give Appendix A a one-sentence opening that says
who should read it ("Read this if you want the per-feature evidence behind
§8's claim; skip it if §8's conclusion is enough"). Right now the appendix is
discoverable only by accident.

## ST3 (STRUCTURE) — §9 partly repeats §§1–8 without adding enough

§9 ("the plan's instances, grounded in pm") is valuable as the *internal*
grounding, but each instance's "prior-work cluster it draws on" subsection
just re-lists sections already read (Blackboard §1, Actor §1, Linda §1...).
That is repetition, not synthesis. Either cut the "prior-work cluster"
subsections (the cross-references are already in §§1–8) or make them earn
their place by saying something *new* about how the cluster applies to that
specific instance. As written they pad a section that is otherwise the most
concrete in the document.

## ST4 (STRUCTURE) — The conclusion has five subsections and restates the contribution four times

The conclusion runs (a)/(b)/(c)/(d) + MMP + "other close prior art" + "read
on the framing" + "coverage gaps" — eight blocks. The contribution sentence
("a data structure that holds unsettled state as first-class, is relational,
and is intelligence-resolved") appears in the intro, the §0 preview, conclusion
(d), and "read on the framing." Four statements of the same sentence. Cut to
two: one in the intro, one in the conclusion. The conclusion can lose either
(a)+(b)+(c) compression or the "read on the framing" recap — both cover the
same three narrowings.

---

# Block 3 — Non-expert accessibility (LOAD-BEARING)

## A1 (ACCESSIBILITY) — The contribution sentence the whole document builds toward is jargon-dense

The single most important sentence in the review — the contribution
statement, conclusion opening — reads: "the plan builds a
work-coordination-and-agency layer over artifacts — a data structure that
holds unsettled state as first-class, that is relational, and that relies on
intelligence to resolve conflicts." The target reader (non-developer) does
not have: "first-class" (the review glosses it 300 lines earlier, in the
intro — the reader has forgotten), "relational" (un-glossed entirely — to a
non-developer this could mean "about relationships" loosely), "unsettled
state." This is the payoff sentence and it is the least accessible sentence
in the document. Proposed rewrite, in the reader's vocabulary:

> "The plan builds something new on top of the project's files: instead of a
> file being a finished document that something else edits, the file keeps
> track of its own half-decided, still-being-argued-over changes, knows how
> it connects to other files, and uses an AI to settle disagreements between
> competing changes — work that until recently no software could do because
> the 'settle the disagreement' step needs judgment, and only a person could
> supply judgment."

That is longer but every word is one the target reader has. Test passed: no
new jargon introduced.

## A2 (ACCESSIBILITY) — Undefined or under-glossed jargon (inventory)

Terms used load-bearingly without an inline gloss the target reader can use:

- **"relational"** (conclusion, §0 preview) — un-glossed. Gloss: "the artifact
  records how it connects to other artifacts, not just its own contents."
- **"superposition"** (§"Tasks as the atom" echoed from plan; §5) — the review
  glosses it parenthetically in §5 ("many possible versions of the document
  are held at once") — good — but uses it in §0/intro context first without
  the gloss. Move the gloss to first use.
- **"stigmergy / stigmergic"** (§5, §9 Instance 2) — §5 glosses it well
  ("indirect coordination: agents change a shared environment..."). But §9
  Instance 1's prior-work cluster and Appendix A use "stigmergically" with no
  re-gloss and a reader who skipped §5 is lost. Either gloss on each use or
  accept §5 as canonical and don't use the adjective form elsewhere.
- **"operational transformation" / "OT"** — §2 glosses by outcome (good) but
  then the acronym "OT" recurs in §2's conclusion and conclusion (b); a
  reader who read the gloss as a story may not have retained "OT". Spell out
  on the §2-conclusion reuse.
- **"DAG"** — does not appear in the current review but *will* if AgentNet /
  ScienceClaw are added (S1, S2). Pre-emptive note: gloss as "a structure of
  steps where each depends on earlier ones and nothing loops back."
- **"oracle"** (§5 Agora-Opt, conclusion) — "a solver oracle," "no oracle to
  ground the judgment." Non-developer reader does not know "oracle" as a CS
  term. Gloss: "a solver oracle — an external tool that can definitively
  check whether an answer is correct."
- **"F1 score"** — will appear if Salemi's numbers are quoted more fully;
  currently the review quotes "13–57% relative gains" without the F1; fine as
  is, but do not add F1 without a gloss.
- **"tuple" / "content-addressable"** (§1 Linda) — "content-addressable pool"
  is glossed obliquely ("whoever wants it picks it up by matching on
  content") — acceptable. "tuple" is left as "data records ('tuples')" —
  acceptable.
- **"throughput" / "2,720.7 MB/s"** (§4 MAIF) — see A4 (scale anchor).

## A3 (ACCESSIBILITY) — Several section openings still fail the "why should I care?" check

Methodology Block 3: a section that opens with a paper citation or a
technical claim has probably failed.

- **§4** opens: "This section covers the work that comes closest to the plan
  — recent enough that it could undercut the plan's claim to be new." Actually
  this one *passes* — it tells the reader the stakes. Good.
- **§6** opens: "The plan makes one ambitious side-claim: that living
  artifacts could change how evolutionary algorithms work." Passes.
- **§7** opens: "The plan states its 'wants' are 'a prompt scaffold, not a
  metaphor'..." — borderline. The reader does not yet know why they should
  care whether wants are a scaffold. Proposed opening: "Can you change what an
  AI does just by telling it to act as if a document 'wanted' something? The
  plan bets yes. This section checks whether that bet has evidence behind it."
- **§3** opens: "The idea of a document that is also a live, working thing is
  not new." Passes — it is a hook.
- **§9** opens: "Section 8 grounded the plan against the tool people use
  today..." — this is a transition, not a benefit statement. The reader does
  not learn what §9 gives *them*. Proposed: "This section is the most
  concrete in the review: for each of the four things the plan actually
  commits to building, it shows what pm does today, what breaks, and what
  changes."
- **§2** opens with a question ("Can many edits happen to one document at the
  same time without a referee?") — good, passes.

Net: §7 and §9 openings should be rewritten to lead with reader benefit.

## A4 (ACCESSIBILITY) — Quantitative claims without scale anchors

- **MAIF "2,720.7 MB/s"** (§4) — the review correctly says this is "a
  throughput-benchmark claim... not a deployed-with-users claim." Good
  framing. But the *number itself* tells the target reader nothing — is
  2,720 MB/s fast? The review's point is "this is the wrong kind of evidence,"
  which it makes — so consider just cutting the number and keeping "MAIF's
  'production-ready' claim is a speed benchmark, not a real-deployment
  claim." The digits add nothing for this audience.
- **"25,000+ task runs ... 4–256 agents ... 8 coordination protocols"**
  (§5, Drop the Hierarchy) — the reader cannot tell if 25,000 runs is a lot.
  Anchor: "25,000+ task runs — a large controlled study, big enough that its
  findings are not noise."
- **"5,006 unique roles emerged from 8 agents"** (§5) — striking but
  un-anchored: is that surprising? Anchor: "5,006 distinct roles invented by
  just 8 agents — i.e., the agents kept inventing new ways to divide the work
  rather than settling into a fixed org chart."
- **"41% and 86.7%" production failure rates** (§5 Semantic Consensus) —
  failure of *what*? The review says "multi-agent failure" — anchor it:
  "between 41% and 86.7% of multi-agent runs fail to complete their task
  correctly — a high enough rate that coordination failure is the field's
  central unsolved problem, not an edge case."
- **"up to a 21% speedup ... up to a 39% slowdown"** (§2 CodeCRDT) — well
  anchored already (the review explains the trade-off). Good.

## A5 (ACCESSIBILITY) — Names dropped with incomplete "what it is / why we mention it"

Methodology requires all three: what it is, what the concept is, why the
analogy helps.

- **"Yjs"** (§2, Appendix A) — glossed as "a ready-made software component
  (Yjs) that implements CRDTs." That covers what it is. Fine.
- **"Hearsay-II"** (§1) — "the 1971–76 speech-understanding system." Adequate
  — the reader does not need more.
- **"GROVE group outline editor"** (§2) — named with zero gloss. The reader
  does not know what GROVE is and does not need to; either gloss ("an early
  shared-document editor") or cut the name and keep "built into an early
  collaborative editor."
- **"CAT7" / "Cognitive Memory Block"** (conclusion, MMP) — "a fixed
  seven-field typed schema (CAT7)." The reader does not know what "typed
  schema" means. Gloss: "a fixed form with seven labelled fields — like a
  structured template every piece of shared knowledge has to fill in."
- **"the cap-set problem"** (§6 FunSearch) — named, glossed as "an open
  problem in pure mathematics." Adequate for the purpose.
- **"contract-net"** — well handled (the subcontracting analogy is exactly
  right for this audience). Model gloss.

## A6 (ACCESSIBILITY) — Unmotivated framing in §8

§8's opening: "This section is load-bearing. The plan owner specifically
asked for it." Telling the reader "the plan owner asked for this" is an
insider signal — the target reader is not the plan owner and does not care
who asked. It also does not tell the reader what *they* get. Replace with the
reader benefit: "This section checks the plan against the most widely-used
tool in this space — Claude Code — so you can see whether the plan is
proposing something Claude Code already does, or something genuinely
missing."

## A7 (ACCESSIBILITY) — Implicit prior-art dependency: §7 leans on a companion review the reader may not have

§7 repeatedly defers to "the companion review `literature-review-user-model.md`"
for the persona-prompting evidence ("its §2," "the Persona Selection Model").
A reader evaluating *this* plan has no reason to have read the other review.
§7's verdict ("persona prompting is an established lever") then rests on
evidence the reader cannot see. Either inline the two or three load-bearing
findings (Salewski expert-persona result; the up-to-30-point drop from
irrelevant persona detail — both are already quoted in §7, good) and drop the
"see companion review §2" pointers, or add a one-line "you do not need to
read the companion review; the findings you need are quoted here." Currently
§7 reads as if it is incomplete without a second document.

---

# Block 4 — Prose

## P1 (PROSE) — "relocated, not eliminated" is repeated to the point of tic

Counted ~9 occurrences of the relocate/not-eliminate construction across
intro, §4, §5, §9, conclusion. By the fourth the reader has it; by the ninth
it reads as anxious. Keep it stated *once* fully (the §5 passage does it
best), and elsewhere refer to it in shorter form ("the relocation argument
above," "as §5 sets out"). Same problem with "corroborates the plan's
direction" — appears 6+ times. Vary or thin.

## P2 (PROSE) — Em-dash overload

The document leans on em-dashes for nearly every mid-sentence turn. Spot
count in the intro alone: 11 em-dash pairs/single dashes in ~600 words.
Methodology Block 4: "dashes-for-drama — used densely they cancel each
other." Convert roughly half to commas, colons, or sentence breaks. Example —
intro: "A thin layer of 'orchestration code' sits between the two: it watches
the data, decides what to do, and rewrites the data." — already fine. But
"the plan's central direction survives this survey, narrowed but intact" then
"— Stated plainly, the plan's direction is: —" stacks dashes and colons.
Pick one mark per sentence.

## P3 (PROSE) — Hedge stacking

§5 and the conclusion stack qualifiers: "the bet rests on a measured
cost-capability gap that is already small; the residual uncertainty is the
benchmark-to-negotiation transfer, not whether cheap models are broadly
capable." Then: "So the correct reading of the threshold finding is not
'cost-stratification is unsafe' and not 'cost-stratification is correctly
staged' — it is..." This triple-negative-then-positive construction is hard
to parse. Rewrite: "The threshold finding does not make cost-stratification
unsafe, and it does not vindicate it either. It makes it a bet — on a moving
cost curve, with privileged participants as the fallback, and the interim
economics as a real open risk."

## P4 (PROSE) — "Strikingly close," "most pointedly," "strong departure" — intensifier creep

The intro and §4 reach for intensifiers to do work the evidence should do:
"strikingly close," "most pointedly," "a strong departure." Cut the
adverbs; let the comparison carry it. "the last twelve months have produced
LLM-agent systems strikingly close to the plan's architecture" → "the last
twelve months have produced LLM-agent systems close to the plan's
architecture" — the section then proves how close; the adverb pre-judges it.

## P5 (PROSE) — §1's "Mostly, yes." / "*Mostly, yes.*" italic-fragment tic

§1 uses italic one-word verdicts: "*Mostly, yes.*", "*partly* true and
*partly* not." These are fine once; §1 does it three times in three
subsections and it becomes a verbal mannerism. Keep one, convert the others
to full sentences.

## P6 (PROSE) — Buried lead in the §4 AutoGen sentence

"Its 'group chat' mode — which sounds the most peer-to-peer — in fact runs
through a group chat manager." The load-bearing claim (AutoGen has a central
manager) is correct but the sentence makes the reader wait through two
dashes. Tighten: "AutoGen's 'group chat' mode sounds peer-to-peer but runs
through a central 'group chat manager' that decides who speaks next."

## P7 (PROSE) — Conclusion (d) sentence is a run-on

"It is **specifying and building the data structure the enabler now permits,
and proving it on a real substrate.**" — then a colon, then three bullets,
then "And the plan proves it by building it, in sequence, on a real substrate
— the four instances Section 9 lays out, carrying the data structure into a
working project-management tool and then (Instance 4) into code itself, not a
research demo." That last sentence has four clauses chained by dashes and
parens. Split: "The plan proves the data structure by building it in
sequence on a real substrate — the four instances of Section 9. It carries
the structure into a working project-management tool, then into code itself.
This is not a research demo."

---

# Citation-graph walk

**Seeds (named before searching, per methodology 5a):**

1. Blackboard / LLM-blackboard revival (Han & Zhang 2507.01701; Salemi
   2510.01285)
2. CRDTs / CodeCRDT (2510.18893) and OT (Ellis & Gibbs 1989)
3. Self-organizing LLM agents — "Drop the Hierarchy" (2603.28990), SwarmSys
   (2510.10047)
4. MAIF (2511.15097) — artifact-centric paradigm
5. Actor model / contract-net (Hewitt 1973; Smith 1980)
6. MemGPT (2310.08560) / LLM-OS / InfiAgent (2601.03204) / "Everything is
   Context" (2512.05470)
7. Evolutionary: Promptbreeder / FunSearch / AlphaEvolve / ADAS
8. Agora-Opt (2604.25847) / Semantic Consensus (2604.16339)

**Direction, range, venues.** Both directions per methodology 5b. Forward
("cited-by"-equivalent) and backward (recent neighbors) via Google Scholar /
arXiv listing search, date-filtered to the last ~12 months, with attention
to the last 30 days. Searched beyond arXiv: OpenReview, emergentmind topic
pages, ResearchGate, lab/industry blogs (Electric, Carvalho). Time spent
~45 min.

**Findings per seed:**

- **Seed 1 (blackboard):** Both abstracts fetched and verified (S9). No newer
  blackboard paper found. The review's §1 treatment is current. Convergence.
- **Seed 3 (self-organizing) — PRODUCTIVE.** Forward walk surfaced **AgentNet
  (arXiv:2504.00587, Apr 2025)** — decentralized evolutionary coordination,
  no orchestrator, built and evaluated. Uncited. See S1. Also surfaced
  **AgentsNet (2507.08616)** — a benchmark for self-organization/coordination
  from distributed-computing primitives; relevant as a *benchmark* the plan's
  future PRs could use, worth a one-line mention in §5 but not load-bearing.
- **Seed 4 (artifact-centric) — PRODUCTIVE.** Surfaced **"Externalization in
  LLM Agents" survey (2604.08224, Apr 2026)** — the umbrella survey of the
  §4/§8 cluster, uncited (S4). Also surfaced the emergentmind
  "Artifact-Centric AI Agent Paradigm" topic page, which confirms MAIF is the
  canonical reference and the review's MAIF treatment is accurate.
- **Seed 6 (memory / file-as-state) — PRODUCTIVE.** Backward/neighbor walk
  surfaced **"Position: Agentic Evolution..." / A-Evolve (2602.00359)** —
  persistent-state-driven evolution, relevant to §6 and §4 (S3).
- **Living-artifacts plain-term search — PRODUCTIVE.** Surfaced
  **ScienceClaw + Infinite (2603.14312, Mar 2026)** — emergent artifact
  exchange, no central coordination, autonomous mutation layer that prunes a
  conflicting artifact DAG. Closest published thing to the
  self-maintaining-artifact idea. Uncited (S2). Also surfaced **"The Last
  Human-Written Paper: Agent-Native Research Artifacts" (2604.24658)** — a
  machine-executable research-package protocol with a "Live Research
  Manager"; relevant to the §"living research workflows" follow-on direction
  the plan names, worth a one-line cite there, not load-bearing.
- **Seed 7 (evolutionary):** Surfaced CodeEvolve, Multi-Agent Evolve, LLM4EO,
  Digital Red Queen — all confirm §6's "LLM-driven evolution is well-trodden"
  point; none does negotiated internal selection; the §6 residual holds.
  Convergence — no new load-bearing cite, but it strengthens §6's "this is
  inherited" framing.
- **Seeds 2, 5, 8:** Convergence. No new load-bearing prior art. CRDT-for-LLM
  industry pattern (Electric, the 2509.11826 paper) already cited. Contract-net
  forward walk surfaced LLM *negotiation* papers (AgenticPay, supply-chain
  bargaining) — these are LLM-negotiation-as-task-domain, not coordination
  substrates; not prior art for the plan; correctly absent.

**Walk verdict.** Four productive seeds, four convergent. The walk found
**three load-bearing uncited papers** (AgentNet, ScienceClaw+Infinite,
Externalization survey) and **two worth a one-line mention** (A-Evolve,
AgentsNet, Agent-Native Research Artifacts). The prior cycle's walk — per the
task framing — apparently walked backward only and missed forward "cited-by"
work; AgentNet (Apr 2025) and the externalization survey (Apr 2026) are
exactly the forward-frontier work a backward-only walk misses. The remedy
held: walking forward this cycle found them.

---

# Summary table

| # | Block | Type | Severity |
|---|-------|------|----------|
| S1 | Substance | Uncited prior art (AgentNet) | High |
| S2 | Substance | Uncited prior art (ScienceClaw) | High |
| S3 | Substance | Uncited prior art (A-Evolve) | Medium |
| S4 | Substance | Missing umbrella survey | Medium |
| S5 | Substance | §4 self-contradiction | Medium |
| S6 | Substance | Single-sourced keystone number | Medium |
| S7 | Substance | Open question presented as answered | Medium |
| S8 | Substance | Cross-study number splice | Medium |
| S9 | Substance | Verification — 5 corrected cites all check out | (positive) |
| S10 | Substance | Reframe mostly consistent; 1 stale, 1 overclaim | Medium |
| S11 | Substance | No engagement with negotiation convergence | Medium |
| ST1 | Structure | Too long; add exec summary | Medium |
| ST2 | Structure | Appendix A under-referenced | Low |
| ST3 | Structure | §9 prior-work subsections repeat | Low |
| ST4 | Structure | Conclusion restates contribution 4x | Low |
| A1 | Accessibility | Contribution sentence jargon-dense | High |
| A2 | Accessibility | Jargon inventory | Medium |
| A3 | Accessibility | §7/§9 openings fail "why care" | Medium |
| A4 | Accessibility | Scale anchors missing | Medium |
| A5 | Accessibility | Name-drops (GROVE, CAT7) | Low |
| A6 | Accessibility | §8 "plan owner asked" insider framing | Low |
| A7 | Accessibility | §7 depends on companion review | Medium |
| P1 | Prose | "relocated not eliminated" tic | Low |
| P2 | Prose | Em-dash overload | Low |
| P3 | Prose | Hedge stacking | Low |
| P4 | Prose | Intensifier creep | Low |
| P5 | Prose | §1 italic-fragment tic | Low |
| P6 | Prose | §4 buried lead | Low |
| P7 | Prose | Conclusion (d) run-on | Low |

---

# Appendix — What prior cycles missed

*(Written after the independent review above, having scanned
REVIEW_CYCLE_1_LIVING_ARTIFACTS.md, REVIEW_CYCLE_2_LIVING_ARTIFACTS.md, and
the response files.)*

- **Cycle 1 and Cycle 2 both walked the citation graph but neither found
  AgentNet (Apr 2025).** AgentNet is over a year old, decentralized, no
  orchestrator, built and evaluated — it should have surfaced on any forward
  walk of the self-organizing-agents seed. The task brief warned that "a
  prior cycle missed recent work by only walking backward"; AgentNet is the
  proof. It is not even recent — it is the *oldest* of my three finds, which
  makes the miss worse: it was available for every prior cycle.
- **Neither prior cycle surfaced ScienceClaw+Infinite (2603.14312).** This is
  more forgivable — it is March 2026 and would not have existed for Cycle 1.
  But it is the closest published artifact-with-conflict-pruning paper and a
  Cycle 2 walk dated after March should have caught it. It is the find that
  most directly tests the plan's self-maintenance novelty.
- **The "Externalization in LLM Agents" survey (2604.08224)** is an umbrella
  survey of exactly the §4/§8 cluster. Prior cycles added InfiAgent and
  "Everything is Context" individually but missed the survey that frames
  them — a sign the prior walk found leaf nodes but not the review node above
  them.
- **What prior cycles did well, and I confirm:** the five corrected-scope
  citations (S9) all verify against their abstracts. The blackboard §1
  rewrite is accurate. The "relocated not eliminated" reframe is honest and
  almost fully consistent (S10 — one stale spot, one mild overclaim). The
  §8→Appendix move improved the document. Cycles 1–2 did real work; the
  contribution is genuinely narrowed-not-collapsed. The gap is purely the
  forward citation walk.
- **Convergence signal:** on everything *except* the citation walk, this
  cycle's findings are mostly phrasing and accessibility nitpicks — a
  convergence signal per methodology step 8. The substance findings are
  almost entirely walk-driven. That means: one more response cycle to absorb
  AgentNet / ScienceClaw / the survey, fix the §4 self-contradiction, and
  tighten accessibility — and the document is done. Do not run a Cycle 4
  unless a fresh walk after the next response finds new frontier work.
