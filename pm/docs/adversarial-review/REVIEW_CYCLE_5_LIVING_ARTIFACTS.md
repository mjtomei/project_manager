# Review Cycle 5 — Literature Review: Living Artifacts

Reviewer: fresh session, blind to prior cycles at time of drafting. Date: 2026-05-15.
Artifact: `pm/docs/literature-review-living-artifacts.md` (~11,700 words).
Methodology: `pm/docs/adversarial-review/METHODOLOGY.md`.

---

## Verdict up front

The document is in good shape. It is honest about inheritance, it narrows its
contribution claims rather than collapsing or overselling them, and the four
sub-claim calibrations in "Read on the framing" are exactly the kind of
defensible-because-narrowed move the methodology asks for. Most of what follows
is phrasing, not substance. There is **one genuinely substantive miss** — a
days-old paper (MEMOREPAIR, arXiv:2605.07242) that is the closest published
work to the plan's self-maintenance mechanism and is uncited — and a cluster
of accessibility findings that, while individually small, add up because the
body still over-relies on a non-developer reading three nested glosses inside
single sentences.

Findings: **23 total — 6 substantive, 17 phrasing/accessibility/prose.**
Convergence: **close, not reached.** The MEMOREPAIR miss must be handled; the
accessibility "gloss-stacking" pattern is a real Block-3 failure; everything
else is convergence-grade nitpicking.

---

## Block 1 — Substance

### S1 (substantive) — MEMOREPAIR is uncited and is the closest prior art on self-maintenance

The citation-graph walk surfaced **"MEMOREPAIR: Barrier-First Cascade Repair in
Agentic Memory" (arXiv:2605.07242, May 2026)**. It is days old, post-dates the
draft, and is not in the references. It is the closest published work to the
plan's *self-maintenance* mechanism — closer than ScienceClaw, which the body
names as "closest published thing to the plan's self-maintenance."

**What MEMOREPAIR actually does** (sourced from abstract / arXiv summary):
the paper "formalizes [a] failure mode as the cascade update problem, where
repair targets the visible derived state of the memory store ... when source
artifacts in agent memory are invalidated, their derived descendants (such as
summaries, cached outputs, or procedures) may remain visible and stale." It
"models agentic memory as a directed provenance graph"; a repair event
"induces a controlled transition from invalidated descendant state to
validated successor state: affected descendants are withdrawn before repair,
successors are constructed from retained support ... republication is
restricted to validated predecessor-closed successors." The induced
publication problem "reduces to maximum-weight predecessor closure and can be
solved exactly by a single s-t min-cut." On ToolBench and MemoryArena it
"reduces invalidated-memory exposure from 69.8–94.3% ... to 0%."

**Why this matters to the plan.** The plan's self-maintenance story is: an
artifact spawns coherence-checks, stale-content sweeps, summary regeneration.
That is *exactly* the cascade-update problem MEMOREPAIR formalizes — when a
plan's motivation changes, the derived PR descriptions go stale. MEMOREPAIR
gives that problem a name, a provenance-graph data model, and an *exact*
algorithmic solution (min-cut). The plan's "self-maintenance task notices
staleness and surfaces a negotiation" is a softer, judgment-based version of
the same move.

**Narrow, don't collapse.** What MEMOREPAIR preempts: the claim that
formalizing "derived artifacts go stale when their source changes, and the
system should repair the cascade" is unprecedented. It is not — MEMOREPAIR
did it last week, with a stronger guarantee (provable 0% stale exposure)
than the plan offers. What MEMOREPAIR does *not* do: its repair is a
deterministic graph algorithm (min-cut over a provenance DAG); it has no
negotiation, no wants, no peer-to-peer task lifecycle, and the artifacts are
passive memory blocks, not agency-bearing peers. Its repair is *centralized*
— a single repair event recomputes the closure — exactly the central
adjudicator the plan relocates away from.

Proposed replacement contribution statement for the self-maintenance discussion
(currently the ScienceClaw paragraph in the exec summary and Appendix B§5):
add one sentence — "MEMOREPAIR (2606.07242, 2026) gives the cascade-update
problem an exact centralized solution over a provenance graph; the plan's
self-maintenance is the decentralized, judgment-resolved counterpart — no
provenance min-cut, but no central repair event either, and the repairing
task negotiates as a peer rather than recomputing a closure." This *narrows*
the self-maintenance novelty to "decentralized, negotiated, judgment-based"
and is more defensible for it. The exec summary's "ScienceClaw ... closest
published thing to the plan's self-maintenance" line is now wrong and should
be softened to "among the closest."

### S2 (substantive) — the negotiation-convergence risk is under-cited given how load-bearing it is

B§5 "Does the negotiation converge?" flags non-termination as an open risk and
the coverage-gaps list repeats it, citing only "multi-agent-debate work" in the
abstract. The walk found this literature is now specific and damaging:
"The Consensus Trap: Rescuing Multi-Agent LLMs from Adversarial Majorities"
(arXiv:2604.17139, 2026) and the multi-agent-debate-stability line document
**sycophantic false consensus** and **oscillation between facts and lies** as
named, measured failure modes — not vague risks. One stability-detection paper
needs a Kolmogorov-Smirnov test on a Beta-Binomial mixture just to *decide when
a debate has converged*, which tells you termination is not free.

This is substantive because the plan's entire "human as boundary" claim rests
on negotiations mostly converging without a human. The document already hedges
this correctly ("goal state ... not a day-one property") but cites it thinly.
Add one terse sentence to B§5: "Named failure modes — sycophantic false
consensus and fact/lie oscillation — are measured in recent multi-agent-debate
work (e.g. the 'Consensus Trap', 2604.17139); the plan's timeout-into-dropped
rule is one mitigation among several and is untested here." This is a
one-sentence add, net-neutral if paired with a cut (see V-pass).

### S3 (substantive) — the evolutionary-computation sliver has new competition

B§6 narrows the evolutionary claim to "negotiated internal selection" — a
candidate that "evaluates its own fitness in context and negotiates its
survival with neighbors." The walk found **CORAL: Towards Autonomous
Multi-Agent Evolution for Open-Ended Discovery (arXiv:2604.01658, 2026)**,
which "brings agent autonomy into the evolutionary loop, replacing rigid search
heuristics with agent-level intelligence at each evolution step ... autonomous
agents that control retrieval, proposal, evaluation, and knowledge
accumulation, while coordinating through shared persistent memory."

CORAL does not fully preempt the sliver — its agents control the *operators*
of an evolutionary loop, not the *selection of themselves as candidates*; an
external loop still drives selection. But it narrows the gap: "agents with
autonomy inside the evolutionary loop" is now built. The honest move is to cite
CORAL in B§6 and re-state the sliver as "selection emerging from the candidates
themselves, not merely autonomous agents operating the loop's machinery" —
which is what B§6 means but does not currently defend against CORAL. One
sentence; pair with a cut.

### S4 (substantive) — the "5–10% semantic residue" number carries more weight than it can bear

CodeCRDT's 5–10% figure appears four times: exec-summary-adjacent reasoning,
conclusion (b), conclusion (c), and B§2, and is explicitly "the load-bearing
number" and "the gap the plan's intelligence-resolved layer fills." The
document *does* flag, twice, that it is one measurement from one 600-trial
preprint on *code* merges and may not transfer to prose/task artifacts. Good.
But the argument still leans on it as the quantitative justification for the
whole intelligence-resolved layer. If that number is wrong for prose artifacts
— and the document admits it might be — conclusion (c)'s "CodeCRDT's own
measured 5–10% semantic residue motivates exactly this layer" loses its
empirical anchor.

This is not a request to add anything. It is a request to *demote* the number:
in conclusion (c), replace "CodeCRDT's own measured 5–10% semantic residue
motivates exactly this layer" with "CodeCRDT measures a non-zero semantic
residue after syntactic merge — evidence the judgment layer has real work to
do, though the rate for prose-and-task artifacts is unmeasured." The argument
survives on the *existence* of a residue, not on the specific percentage. This
also removes one of four repetitions of the figure (Block-2 win).

### S5 (substantive) — Instance 3's "tuple space" claim is asserted, not argued

Instance 3 says "the artifact substrate pm then hosts is a tuple space
(Appendix B §1) — coordination through a shared pool rather than through a
central orchestrator." B§1 itself is more careful: it says the *task queue
inside one artifact* is "structurally, a tuple space scoped to one document."
But Instance 3 elevates this to the *whole substrate* being a tuple space.
That is a stronger claim and it is not obviously true: a tuple space is a
single global pool with content-addressed `in`/`out`/`rd`; the plan's substrate
is many per-artifact queues plus cross-artifact negotiation. The plan is at
most a *federation* of tuple spaces, not one. Either narrow Instance 3's
sentence to match B§1 ("each artifact's task queue is a tuple space scoped to
that document") or argue the federation claim explicitly. Currently it reads as
a vocabulary flourish that B§1 does not actually support.

### S6 (substantive, minor) — the MMP "production" hedge is repeated three times and still slightly overstated

The MMP "running in production across three reference deployments — running,
but in the authors' own reference implementations, not verified commercial
third-party adoption" caveat appears in the exec summary, the conclusion's MMP
section, and the references entry. Three times is twice too many. More
importantly: the document treats MMP as "the single closest work" and "the
closest prior art on the *mechanics*," yet MMP is an unverified-adoption 2026
preprint. The conclusion's "MMP runs that" (re typed, semantically-merged,
cross-session shared memory) states as fact something the document elsewhere
hedges. Pick one register: either MMP demonstrably runs it (then drop the
hedge) or it is a preprint claim (then "MMP claims to run that"). Keep the
hedge once, in the references entry; the conclusion should say "MMP specifies
that."

---

## Block 2 — Structure and readability

### St1 — the exec summary and the conclusion say the same thing twice, at length

The executive summary's "What is new is putting *agency* ... into the file
itself, as a general substrate" and the conclusion (d)'s three-bullet
"unsettled state / relational / intelligence-resolved" breakdown are the same
contribution claim stated twice. The conclusion also restates the one-sentence
contribution verbatim-ish at the top of the Conclusion *and* again as (d). A
reader who reads both ends gets the thesis three times. Keep the
three-property breakdown in the conclusion (it is the precise version); cut the
exec summary down to a pointer ("the contribution, stated precisely, is in the
conclusion"). See V-pass for the word count.

### St2 — "prior art in brief" partly duplicates the conclusion's framing list

The "Prior art in brief" eight-cluster list and the conclusion's "Read on the
framing" four-calibration list overlap heavily (both tell the reader the
determinism claim is the strong half, the central-scheduler claim is the weak
half, the evolutionary claim is mostly inherited). This is the intended
body/appendix split working *partly* — but the same calibrations land twice in
the body. Consider making "prior art in brief" purely descriptive (what each
cluster *is*) and letting "Read on the framing" carry all the *calibration*.

### St3 — Appendix B§8 is a 4-sentence stub that adds nothing Appendix A doesn't

B§8 says "the full feature-by-feature walk is in Appendix A" and then restates
A's conclusion in two sentences. It is a pointer dressed as a section. Either
fold its one new sentence (InfiAgent / "Everything is Context" as the frontier)
into the "prior art in brief" Claude Code bullet and delete B§8, or delete the
pointer sentences. As written it is pure overhead.

### St4 — no diagram, and this document badly wants one

Eleven thousand words describing a data structure with no figure. A single
diagram — "passive data + separate intelligence + orchestration glue" on the
left, "fused living artifact" on the right, with the task queue / negotiation
history / wants / self-maintenance schedule as labelled compartments — would do
more for a non-developer than three pages of prose. The methodology's Block 2
explicitly asks "what figures or tables would be most valuable." This is the
answer. A second candidate: a table mapping each of the 8 prior-art clusters to
"what it gives the plan / what limited it / what LLMs change" — the document
already has this content in prose four times over.

---

## Block 3 — Non-expert accessibility (load-bearing)

The body restructure helps: the four-instance section is genuinely the most
concrete part and a non-developer can follow it. But the body still fails the
target reader in one systematic way.

### A1 — gloss-stacking: sentences carry three nested parenthetical glosses

The single worst accessibility pattern. Conclusion's opening sentence:

> "the plan builds a work-coordination-and-agency layer over artifacts — a data
> structure that holds unsettled, in-flight state as first-class (the
> half-decided, still-being-argued-over version of an artifact, stored as
> seriously as the finished version), is relational (it records how it connects
> to other artifacts, not just its own contents), and is intelligence-resolved
> (an AI settles conflicts) — and the closest prior art, the Mesh Memory
> Protocol, addresses a different problem, not a competing one."

That is one sentence, ~80 words, three parenthetical glosses, two em-dash
clauses, and a citation. The target reader cannot hold it. The Introduction's
"What surrounds the plan" closing sentence has the same shape — "(it is
*relational* — the artifact records how it connects to other artifacts...)"
nested inside a sentence that also glosses "first-class" and "superposition."

**Proposed fix:** make the contribution a short bulleted list, not a sentence.
The conclusion (d) *already does this* with the three-property bullets — so the
one-sentence version at the top of the conclusion is redundant *and*
inaccessible. Delete it; let the bullets carry it. For the Introduction's
"What surrounds the plan" sentence, split: "The plan builds something new on
top of the project's files. The file keeps its own half-decided changes. It
records how it connects to other files. And it uses an AI to settle
disagreements between competing changes — work that, until recently, only a
person could do." Four short sentences, zero parentheticals, no new jargon.

### A2 — "first-class" is glossed three times and still not clearly

"First-class" gets a parenthetical in the Introduction, another in the
Conclusion's opening sentence, and a third in conclusion bullet (d). Three
glosses of the same term means none of them is trusted to land. The cleanest
gloss is the bullet-(d) one ("the artifact's state is not a single committed
value"). Gloss it *once*, on first use in the Introduction, then use it
plainly. A non-developer does not need "first-class" at all — it is CS jargon
for "treated as seriously as X." Consider just writing "treated as real,
stored state" and dropping the term.

### A3 — "DAG" used unglossed in the body-adjacent text and references

"AgentNet ... over an adaptive DAG" (Instance-lead text references Appendix B,
but B§4 and B§5 and five reference entries use "DAG"). The target reader does
not know "directed acyclic graph." First use in B§4 ("over an adaptive DAG with
no central orchestrator") needs "— a dependency graph with no cycles —" inline.
Same for "min-cut" if S1's MEMOREPAIR sentence is added: gloss as "a standard
graph algorithm" or cut the term.

### A4 — "superposition" is physics jargon doing decorative work

The Introduction glosses it ("many possible versions of the document held at
once, none yet the final one") but the plan's own text and B§5 ("proposals
exist in superposition") use it as a load-bearing term. The gloss is fine; the
issue is the word earns nothing the gloss doesn't. A non-developer reads
"superposition" and thinks quantum mechanics. Recommend: keep the plain-English
gloss as the primary phrasing and drop "superposition" to a parenthetical
("many candidate versions held at once — the plan calls this *superposition*")
or cut it. Do not lead with the physics word.

### A5 — "stigmergy / stigmergic" used without the reader being told to skip it

B§5 introduces "stigmergy" with a good gloss (ants, pheromone trails) but then
B§4-adjacent and the SwarmSys bullet use "stigmergic" and "pheromone-like
traces" as if known. This is appendix material so the bar is lower, but the
SwarmSys quote ("lightweight, pheromone-like traces") lands in B§4's
neighbourhood. Acceptable in an appendix; flagging only because the methodology
says be aggressive. Lowest-priority accessibility finding.

### A6 — "Why should I care?" check: B§2 and B§4 open with definitions, not benefits

B§2 opens "Can many edits happen to one document at the same time without a
referee deciding the order?" — that is actually a *good* opening (a question
the reader can see the stakes of). B§4 opens "This section covers the work that
comes closest to the plan" — fine. B§6 opens "The plan makes one ambitious
side-claim" — fine. Most section openings pass. The one that fails: B§1 opens
"Before trusting the plan's claim to be 'a new kind of coordination,' a reader
should know what the old kinds were" — this is fine actually. The body sections
mostly pass the check; this is a near-clean result. Noting it as a *positive*.

---

## Block 4 — Prose craft

### P1 — em-dash density

Counted on a sample: the conclusion's opening sentence has two em-dash clauses;
the exec-summary bottom-line sentence has one plus three parentheticals; B§5's
"Drop the Hierarchy" hybrid paragraph has four em-dashes in five sentences.
Em-dashes used this densely stop emphasizing. Convert roughly half to periods
or commas. Specific: B§5 "the plan does not eliminate adjudication — nothing
could — it *relocates* it" → "the plan does not eliminate adjudication; nothing
could. It relocates it."

### P2 — "the load-bearing number / the load-bearing half / load-bearing claims"

"Load-bearing" appears at least five times as the document's tic for
"important." It is methodology-vocabulary leaking into the artifact. Replace
with the actual reason each thing is important: "the load-bearing number" →
"the number the plan's case leans on"; "the load-bearing half" → "the half of
the claim that actually holds." At minimum cut to two uses.

### P3 — "the plan should" repetition

"The plan should narrow," "the plan should cite," "the plan should adopt the
word," "the plan should claim the lineage proudly," "the plan's own text should
drop" — this construction appears ~12 times. It is correct (the review is
advisory) but monotonous. Vary: some can become "the plan's text would be
stronger if," some can be folded into the coverage-gaps list, some can be
imperative once ("Narrow that sentence").

### P4 — hedge audit

Mostly clean. Real hedges on real uncertainty ("may differ," "untested,"
"unestablished") earn their place. One unearned: exec summary "the plan should
claim less as brand-new than it *might want to*" — "might want to" is a
throwaway; cut to "the plan should claim less as brand-new." Another: "the
finding usually has a time dimension the plan's framing already accounts for"
(B§5 intro) — "usually" hedges a claim the section then makes confidently; cut.

### P5 — "genuine departure" / "genuine shift" / "genuinely new"

"Genuine" appears as the document's reassurance word four times in B§4 alone
("a genuine departure," "the genuine shift," and twice more). When a document
has to keep telling you something is genuine, it reads as protesting. Cut to
one use; let the point-by-point comparison carry the genuineness.

---

## Step 5 — Citation graph walk

**Seeds (8), chosen as most load-bearing references:**
1. AgentNet (arXiv:2504.00587) — the strongest *built* decentralized-coordination instance.
2. "Drop the Hierarchy" (arXiv:2603.28990) — the load-bearing 25,000-run study.
3. MMP (arXiv:2604.19540) — named "single closest work."
4. CodeCRDT (arXiv:2510.18893) — source of the load-bearing 5–10% figure.
5. ScienceClaw + Infinite (arXiv:2603.14312) — named closest self-maintenance prior art.
6. "Intermediate Artifacts as First-Class Citizens" (arXiv:2605.12087) — first-class-artifact data model.
7. Promptbreeder (ICML 2024) / A-Evolve (arXiv:2602.00359) — evolutionary-computation pillar.
8. MAIF (arXiv:2511.15097) — the "artifact-centric paradigm" precedent.

**Method:** Google Scholar / arXiv listing forward ("cited by" and topic
co-occurrence) and backward (reference scan), date-restricted to the last ~6
months, plus plain-topic searches beyond arXiv. ~50 minutes.

**Coverage by seed:**

- **AgentNet / "Drop the Hierarchy":** forward walk surfaced SOAN
  (arXiv:2508.13732, "Self-Organizing Agent Network") — checked the abstract;
  it is a *structure-driven orchestration* framework that encapsulates
  workflow units as agents for modularity. It is orchestration-centric, not a
  negotiating-artifact substrate; **not a miss**, correctly outside scope.
  No new decentralized-coordination paper closer than what is cited.
- **MMP / "Intermediate Artifacts":** forward walk surfaced **MEMOREPAIR
  (arXiv:2605.07242, May 2026)** — see finding S1. **This is the one real
  miss.** Days old; closest published work on the self-maintenance / stale-
  derived-artifact mechanism. Also surfaced SemanticALLI (pipeline-aware
  caching, first-class cacheable intermediate representations) and MEMRES
  (dependency resolution) — both adjacent but clearly out of scope; not misses.
- **CodeCRDT:** backward and forward walk found nothing closer on
  CRDT-for-LLM-agents than the three works already cited (CodeCRDT, the
  Electric write-up, arXiv:2509.11826). Clean.
- **ScienceClaw:** forward walk found no closer self-maintenance system *except*
  MEMOREPAIR (above). Clean otherwise.
- **Promptbreeder / A-Evolve:** forward walk surfaced **CORAL
  (arXiv:2604.01658, 2026)** — see finding S3 — and CodeEvolve (open-source
  AlphaEvolve-style framework, clearly inherited-territory, not a miss).
  CORAL narrows the B§6 sliver and should be cited.
- **MAIF:** no new artifact-centric-paradigm paper found beyond what is cited
  (MAIF, Ψ-Arch, "Intermediate Artifacts," LSS). Clean.
- **Convergence / termination cluster** (searched as a topic, not a seed,
  because B§5 flags it as a gap): surfaced "The Consensus Trap"
  (arXiv:2604.17139) and the multi-agent-debate-stability line — see S2.
  Not a "missing prior art that preempts" finding, but the convergence-risk
  citation in B§5 should be made specific instead of vague.

**Coverage summary:** the walk found **one genuine miss (MEMOREPAIR)**, **one
near-miss worth citing (CORAL)**, and **one citation that should be made
specific (Consensus Trap line for the convergence risk)**. Everything else the
walk turned up is either already cited or correctly out of scope. For a Cycle-5
review of a heavily-revised document this is a near-converged result on the
citation front — but MEMOREPAIR is genuinely close and genuinely uncited, so
the front is not closed.

---

## Step 10 — Whole-document verbosity pass

Read start to finish hunting for text verbose relative to its point.

**Kinds of cuts found:**

1. **Triple-stated contribution** (St1, A1). The one-sentence contribution
   statement appears in the exec summary, at the top of the Conclusion, and as
   conclusion-(d)'s bullets. Keep the bullets, cut the other two to pointers.
   Estimated cut: **~180 words.**
2. **Repeated MMP "production" hedge** (S6) — stated three times. Keep once.
   Estimated cut: **~60 words.**
3. **Repeated 5–10% CodeCRDT figure** (S4) — appears four times with its
   caveat re-attached twice. Keep two appearances, one with caveat.
   Estimated cut: **~70 words.**
4. **B§8 stub** (St3) — ~90 words, of which ~70 are pointer overhead.
   Estimated cut: **~70 words.**
5. **"Prior art in brief" / "Read on the framing" calibration overlap** (St2).
   The determinism-half / scheduler-half calibration is stated in both.
   Estimated cut: **~90 words.**
6. **Deadwood and hedge stacking** (P2, P4) — "load-bearing" ×5, "genuine" ×4+,
   "the plan should" monotony, "might want to," "usually." Trimming the tics
   and the unearned hedges: **~60 words.**
7. **Instance-section restatement.** Each of the four instances ends with a
   "What it enables" paragraph that partly restates the "Living-artifact
   version" paragraph above it (Instance 1's "the hand-run coherence loop
   becomes a standing property" ≈ "the coherence-check ... becomes a
   self-maintenance task"). Tighten each by one sentence: **~80 words.**
8. **Conclusion (b) is one sentence longer than its point.** "You could not put
   open-ended judgment inside the structure, because open-ended judgment did
   not exist as a component you could instantiate cheaply and ubiquitously" —
   the preceding sentences already said this. Cut: **~30 words.**

**Total estimated cuttable: ~640 words (~5.5% of the document).** The document
is *not* tight — but it is far from the bloat the methodology's step-9 warning
describes. The verbosity is concentrated in repetition of the contribution
claim and the two load-bearing numbers, not in diffuse padding. Cutting the
~640 words while adding the S1/S2/S3 sentences (~120 words total) nets a
**~520-word reduction** — step-9-compliant if the response applies it.

The instance sections, B§1, B§2, B§3, B§6, and B§7 are genuinely tight — they
make their point and stop. Reporting that as a partial convergence signal.

---

## Restructure assessment — does body / Appendix B work?

**Mostly yes.** The body (exec summary, intro, four instances, prior-art-in-brief
stub, conclusion) is now followable by a non-developer in a way the old
all-survey version would not have been. The four-instance section is the best
thing in the document — concrete, pm-grounded, before/after. Moving the
system-by-system survey to Appendix B was the right call.

**Two problems:**

1. **The split leaks calibration into both halves** (St2). "Read on the framing"
   and "prior art in brief" both carry the four sub-claim narrowings. The body
   should describe; the conclusion should calibrate; pick one.
2. **B§8 is a fragment** (St3) — the split produced one section that is just a
   pointer. Fold it into the Claude Code bullet.

The appendix split *helps* more than it *fragments* — but the "prior art in
brief" stub is doing double duty (descriptive summary *and* calibration
preview) and would be cleaner as purely descriptive.

---

## Convergence verdict

**Not yet converged — but one substantive cycle from it.**

The substance is sound and the contribution claims are well-narrowed. But this
cycle found a genuine, uncited, days-old closest-prior-art paper (MEMOREPAIR)
on the plan's self-maintenance mechanism — that is not a nitpick, and a Cycle-5
review surfacing real prior art means the citation front is not closed. S2 and
S3 are smaller but real. S4–S6 are substantive-flavored but really about
*how a claim is stated*, not whether it holds.

Blocks 2–4 are convergence-grade: the findings are repetition, em-dash density,
tic words, one missing diagram. The accessibility findings (A1, A2) are a real
Block-3 failure pattern — gloss-stacking — but the fix is mechanical (split
sentences, bullet the contribution) and introduces no new substance.

**What the next cycle points toward:** apply MEMOREPAIR (S1), cite CORAL (S3),
make the convergence-risk citation specific (S2), demote the 5–10% figure (S4),
de-stack the glosses (A1/A2), add the diagram (St4) — and *net-cut ~520 words*
per step 9. After that, the document should be at genuine convergence: a
Cycle-6 review would be left with phrasing only. The recommendation is **one
more full cycle, then stop.**

---

## Appendix — what prior cycles missed

*(Scanned after the independent review above was drafted.)*

Files reviewed: `REVIEW_CYCLE_1`–`4` and response files in
`pm/docs/adversarial-review/`. Observations on what those cycles did not catch:

- **MEMOREPAIR (S1) was unavailable to prior cycles** — it was posted in May
  2026, so cycles 1–4 could not have found it. This is the expected behaviour
  of step-5c: the most damaging misses come from the last 30 days. It is a
  miss *of the document*, not of the prior reviewers — but it confirms the
  methodology's warning that every cycle must re-walk, because the prior-art
  frontier moves under the document.
- **CORAL (S3)** likewise post-dates earlier cycles' likely walk windows; the
  evolutionary-computation section has been narrowed across cycles but no prior
  cycle had CORAL to test the narrowed sliver against.
- **The gloss-stacking pattern (A1)** appears to be a *product of* prior
  cycles: each cycle that flagged a jargon term got a parenthetical gloss added
  in response, and those glosses accumulated into the three-nested-gloss
  sentences this review flags. This is exactly the step-9 growth-bias warning
  playing out in the accessibility dimension — prior cycles fixed jargon by
  *adding*, and no cycle ran the de-stacking cut. The standing step-10 pass
  should have caught it earlier.
- If prior cycles already flagged the missing diagram (St4) and it was not
  added, that is a standing unaddressed Block-2 finding and should be escalated
  rather than re-deferred.
