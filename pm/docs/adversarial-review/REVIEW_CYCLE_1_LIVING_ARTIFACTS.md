# Adversarial Review — Cycle 1 — Literature Review: Living Artifacts

**Artifact:** `pm/docs/literature-review-living-artifacts.md` (~10,931 words)
**Reviewer:** fresh session, blind to prior cycles
**Date:** 2026-05-15
**Methodology:** `pm/docs/adversarial-review/METHODOLOGY.md` — four blocks + step-5 citation walk + "narrow the contribution; don't collapse it"

---

## Headline verdict

The review is well-written, intellectually honest in tone, and the historical survey (§§1–3, 6) is genuinely good. But it has **one substantive problem that the whole document is built around and does not survive the citation walk**: the citation walk surfaced a 2026 paper — **MAIF (arXiv:2511.15097), "Enforcing AI Trust and Provenance with an Artifact-Centric Agentic Paradigm"** — that independently proposes the *exact headline move* the review claims is the plan's unclaimed contribution: making a persistent, intelligence-carrying data artifact (not a task) the unit that drives agent behavior. The review's central framing — "we specify and build a new data structure ... an old vision newly enabled by LLMs ... the three closest works are narrower slices, none building the general artifact data structure" — is **false as written**. There is now a named, published, claimed-production artifact-centric paradigm. The contribution must be narrowed (not collapsed), and the review's entire "close prior art corroborates, does not preempt" section needs rewriting.

That is a Cycle-1-appropriate substantive finding. There are 8 more substantive findings and a tail of accessibility/prose findings. The review needs significant work — primarily a re-grounding of the contribution claim against prior art the current draft did not search for.

---

# Block 1 — Substance

## S1 (SEVERE) — MAIF preempts the headline framing; the review never searched for it

The review's contribution statement, stated four times (intro, §0 "What surrounds the plan", conclusion (d), and the closing "close prior art" section): *"the plan specifies and builds a new data structure for artifacts — non-deterministic, relational, intelligence-resolved — an old vision newly enabled by LLMs"* and *"What none of [the close works] does is build the general artifact data structure ... That is the plan's job, and it is unclaimed."*

**This is preempted.** The citation walk found:

**MAIF — "MAIF: Enforcing AI Trust and Provenance with an Artifact-Centric Agentic Paradigm" (arXiv:2511.15097, Nov 2025).** From the paper (verified via fetch):
- It proposes an **"artifact-centric AI agent paradigm [that] drives behavior through persistent, verifiable data artifacts rather than ephemeral tasks."** That is, verbatim, the plan's headline move ("the unit itself carries both [content and intelligence] ... orchestration is what emerges when units of this kind interact").
- Agent operations are reframed as **"evolution of the MAIF" rather than discrete task completion** — the plan's "tasks as proposals in motion against the artifact."
- It **"integrates intelligence into the data layer through embedded semantic vectors, knowledge graphs, and trust-aware attention mechanisms"** — the plan's "data + intelligence fused into a single unit."
- It claims a **production-ready implementation at TRL 7–8** — i.e. it is *not* "an academic demonstration not deployed in a real tool," which is the precise differentiation the review leans on against CodeCRDT/SwarmSys.

The "narrow the contribution; don't collapse it" procedure must be run. Here it is:

**What MAIF actually does** (from abstract + body):
- Makes a persistent data artifact (the Multimodal Artifact File Format container) the unit agents act on, not tasks.
- Embeds semantic representation + provenance + access control *into the artifact*.
- Reframes agent work as artifact evolution.
- Claims production readiness.
- **Does NOT** address concurrent agent edits, merge, or conflict resolution (verified — "the paper does not address concurrent agent edits or conflict resolution mechanisms"). Its focus is trust/provenance/auditability, not negotiation.
- **Does NOT** do peer-to-peer negotiation, "wants," or self-maintenance — it is artifact-as-trust-substrate, not artifact-as-negotiating-peer.

**What the plan does that MAIF does not:**
- Concurrent in-flight proposals in superposition; conflict resolution by intelligence.
- Peer-to-peer negotiation among tasks with no central arbiter.
- Anthropomorphized "wants" → self-maintenance tasks the artifact spawns.
- The privileged-participant gradient.

**Computed intersection (what MAIF preempts):** The bare framing "make a persistent data artifact, not a task, the unit; fuse intelligence into the data layer; it is an old idea LLMs now enable" is **no longer the plan's to claim as unclaimed**. MAIF claims exactly that, with a production claim.

**Residual contribution (the narrowed claim that survives):** The plan's defensible, narrower contribution is *not* "artifact-as-unit" — that is now shared prior art. It is the **negotiation-and-conflict layer on top of artifact-as-unit**: concurrent in-flight proposals resolved by LLM reasoning against an integrity constraint, with no central arbiter, with anthropomorphized self-maintenance ("wants"). MAIF is artifact-centric *for trust*; the plan is artifact-centric *for decentralized conflict resolution*. That is a real, statable difference — but it is much narrower than "we build the artifact data structure no one has built."

**Proposed replacement contribution statement:**
> "An artifact-centric paradigm — making a persistent data artifact, rather than an ephemeral task, the unit agents act on — has independent recent precedent (MAIF, 2025, for trust/provenance). The plan's contribution is narrower and specific: a *negotiation-and-conflict layer* for artifact-centric systems. Where MAIF makes the artifact a verifiable trust substrate, the plan makes it a substrate for *decentralized conflict resolution* — concurrent in-flight proposals, held in superposition, resolved by LLM reasoning against an integrity constraint with no central arbiter, and self-maintenance generated by anthropomorphized 'wants.' The contribution is the conflict-resolution and negotiation semantics, not the artifact-as-unit move itself."

This is failure mode B avoided (the review currently holds the line too hard — "unclaimed," "the plan's job") and failure mode A avoided (MAIF does *not* do negotiation, so the contribution does not collapse to zero).

## S2 (SEVERE) — "no academic close work is deployed" is now false; the differentiation against all three close works rests on it

The review repeatedly distinguishes the plan from CodeCRDT, SwarmSys, and "Drop the Hierarchy" with the *same* move: *"none of them deployed in a real tool"* / *"academic demonstrations on narrower slices"* / *"not one of them saw commercial or real-world deployment."* That clause is doing enormous load-bearing work — it appears in the intro, §2, §4, §5, and the conclusion.

The walk breaks it twice:
- **MAIF** claims TRL 7–8 production readiness (S1).
- **Mesh Memory Protocol (MMP, arXiv:2604.19540, April 2026)** — see S3 — explicitly states **"currently deployed in production"**, with the `sym-mesh-channel` plugin having passed Anthropic's Claude Plugin Directory review in April 2026.

So the "no one has deployed this" differentiator is no longer available as a blanket move. The review can still distinguish on *substance* (MAIF doesn't negotiate; MMP's blocks are immutable — see S3), but it must stop using "not deployed" as the differentiator. Right now, if a Cycle-2 reader knows about MAIF/MMP, the review reads as not having done its homework.

## S3 (SEVERE) — Mesh Memory Protocol is direct, un-cited prior art for §2 and the "relational" pillar

**MMP — "Mesh Memory Protocol: Semantic Infrastructure for Multi-Agent LLM Systems" (arXiv:2604.19540, April 2026).** Verified via fetch. This is the single closest miss for §2 ("Concurrent shared state") and conclusion (d)'s "relational" pillar:
- It is a **shared-memory data structure for multi-agent LLMs** — the plan's exact substrate question.
- It defines **CAT7, a seven-field typed schema** (focus, issue, intent, motivation, commitment, perspective, mood) for "Cognitive Memory Blocks" — i.e. a *structured artifact schema*, which is literally the plan's "Artifact schema sketch" PR.
- It handles **concurrent contributions via per-field semantic evaluation** ("SVAF: Symbolic-Vector Attention Fusion: per-field evaluation with role-indexed weights determining admission decisions") — this is *intelligent, semantic, per-field merge of concurrent edits*, which the review claims (conclusion (c)) is "the part that was impossible before, and the part the prior visions could only gesture at."
- It uses **content-hash keys with structured lineage forming a DAG** — the plan's "relational ... carries its relations, negotiation history, cross-artifact references."
- **Role-indexed weights determining admission** is structurally the plan's **privileged-participant gradient**.

The review's conclusion (c)/(d) says intelligent conflict resolution and a relational structure are the genuinely new, LLM-enabled parts. MMP is a 2026 paper that *builds exactly that* — typed schema, semantic per-field merge, lineage graph, role-weighted admission — and ships it. This is not a peripheral miss; it sits on the plan's two of three headline pillars (relational, intelligence-resolved).

**The honest differentiation that survives** (narrow, don't collapse): MMP's CMBs are **immutable once emitted** — "the system does not support concurrent edits; CMBs are immutable; updates occur through new remixed entries." The plan's artifact holds **mutable in-flight proposals in superposition** and tasks that *negotiate* (counter-propose, fold, dissipate). MMP does *admission filtering* (a receiver decides whether to accept an incoming block); the plan does *multi-party negotiation* (proposals reshape each other before any commit). That is a real difference. But the review must:
1. Cite MMP in §2 and the conclusion.
2. Re-state the "intelligence-resolved" pillar as "*negotiated* conflict resolution" (multi-party, proposals reshape) vs MMP's "*admission-filtered* conflict resolution" (per-field accept/reject).
3. Drop the claim that intelligent semantic merge is unbuilt — MMP built a version of it.

## S4 (SUBSTANTIVE) — "Semantic Consensus" preempts the §5 / conclusion framing of the integrity problem

The walk found **"Semantic Consensus: Process-Aware Conflict Detection and Resolution for Enterprise Multi-Agent LLM Systems" (arXiv:2604.16339, April 2026).** It names **"Semantic Intent Divergence"** — "cooperating LLM agents develop inconsistent interpretations of shared objectives due to siloed context" — as a formally-unaddressed root cause of multi-agent failure (it cites production failure rates of 41–86.7%). This is *precisely* the plan's "artifact integrity" problem — the artifact stops cohering when concurrent tasks pull it in inconsistent directions. The review presents the integrity problem as something only CodeCRDT has "measured the size of" (the 5–10% number). Semantic Consensus both names the problem formally and proposes a resolution mechanism. It should be cited in §5 and/or the conclusion as either corroboration or closer prior art for the integrity construct. At minimum the review can no longer imply the semantic-coherence-of-concurrent-edits problem is un-named in the literature.

## S5 (SUBSTANTIVE) — "Drop the Hierarchy"'s finding is mis-stated in a way that flatters the plan; the time-relativity rebuttal partly hand-waves

I verified the abstract. Two problems.

(a) **The hybrid finding is stronger against the plan than the review admits.** The paper's headline is that the *Sequential* protocol — which has **fixed ordering** (a structural scaffold) — beats *both* centralized *and* fully-autonomous self-organization. The review handles this (§5, third bullet) by saying "fixed ordering is a structural prior, not an arbiter" and "the plan's privileged-participant gradient is itself a deliberate non-flat structure." That is fair *as far as it goes*. But the review then says the plan's "no central arbiter stays as its framing" and presents the finding as "a tuning result, not a refutation." It is closer to a refutation of *pure* self-organization than the review concedes: the paper found fully-autonomous coordination *underperforms* the structured hybrid by a wide margin (44%). The plan's §"No central arbiter" and §"Tasks as the atom" describe something much closer to *pure* emergence ("there is no point in time when the edit is being reviewed", "proposals exist in superposition"). The review should state plainly: *the empirical result says some imposed structure beats none, and the plan's design as written under-specifies how much structure it keeps.* Right now the review resolves the tension by quietly redefining "no central arbiter" to mean "no central *adjudicator*, structure OK" — which is a reasonable reading, but the plan text itself does not say that, so the review is doing the plan's narrowing *for* it and then crediting the plan with a framing that survives. That is the "keep the framing" shading into overclaim that the task asked me to pressure-test. **It does shade into overclaim here.** Recommended fix: explicitly flag that the plan's text needs to adopt the narrower "no central adjudicator" wording, rather than asserting the plan's existing framing already survives.

(b) **The time-relativity rebuttal to the strong-vs-weak-model finding is partly hand-waving.** The review's rebuttal (§5, final paragraph): the strong-model-privilege finding is "a snapshot of a moving floor," cost tiers descend, privileged participants cover the interim. The descending-floor premise is plausible but **asserted, not cited** — there is no reference for "the self-organization floor descends as the frontier rises." More importantly, the rebuttal **changes the subject**. "Drop the Hierarchy"'s finding is not just "cheap models can't self-organize *yet*"; it is that below a threshold, autonomy *actively reverses and hurts* performance. The plan's cost-stratification proposes to *demote routine specializations to cheaper intelligence*. The rebuttal says privileged participants are the safety net — but if a cheap task's autonomous negotiation produces actively-worse-than-structured output, the safety net is catching a steady stream of degraded proposals, which is a throughput/cost problem the rebuttal never addresses. The rebuttal answers "is it unsafe?" (no, watchers catch it) but not "is it economical?" (unclear — you may be paying cheap-model costs to generate proposals a watcher then has to redo). The review should either (i) cite something for the descending-floor claim and concede the economic question is open, or (ii) drop the confident "cost-stratification is correctly staged" and call it an open risk. As written it is a rebuttal that sounds airtight and isn't.

## S6 (SUBSTANTIVE) — the "non-deterministic" pillar is the weakest of the three and is under-defended

Conclusion (d) lists three properties of the new data structure: non-deterministic, relational, intelligence-resolved. The review defends "relational" (negotiation history, references — though see S3, MMP does this) and "intelligence-resolved" (the LLM-as-primitive argument — though see S3/S4). But **"non-deterministic" is barely defended and is the most slippery of the three.** The review defines it as "holds proposals in superposition ... represents the unresolved, not just the resolved." But:
- A database with a pending-writes table, or a git repo with multiple open branches, also "represents the unresolved." Holding in-flight state is not novel and not what "non-deterministic" usually means.
- "Non-deterministic" properly means *the same inputs can produce different outputs*. That is true of any LLM-backed system and is a property of the *intelligence*, not the *data structure*. Calling the data structure non-deterministic is close to a category error.

The review should either (a) drop "non-deterministic" from the three-pillar headline and replace it with something it can defend — e.g. "*superpositional*: the structure is a first-class representation of multiple unresolved candidate states, not a single committed value" — or (b) defend "non-deterministic" properly by distinguishing it from a pending-writes table / multi-branch repo. As it stands, the headline contribution statement leads with its weakest, least-defined word. (This also matters for accessibility — see A-block; "non-deterministic" is undefined jargon.)

## S7 (SUBSTANTIVE) — §6 (evolutionary computation) honestly concedes the EA direction is mostly preempted, but the conclusion does not carry that concession forward

§6 does the "narrow, don't collapse" move well: it concedes Promptbreeder/FunSearch/AlphaEvolve/ADAS already loosened two of three pillars, and isolates "negotiated internal selection" as the unclaimed sliver. Good. But the conclusion's "Honest read on the framing" lists "that living units open a different mode of evolutionary computation" among "four boldest moves [that] all hold." That is inconsistent with §6's own finding that the EA direction is *mostly inherited* and only a narrow sliver is unclaimed *and untested*. The conclusion overstates what §6 actually established. Fix: the conclusion's framing-summary bullet on EA should read "...the evolutionary-computation claim narrows to a single untested sliver (negotiated internal selection), inheriting the rest openly" — not "holds."

## S8 (MODERATE) — the actor-model "central scheduler" rebuttal is correct but the review spends 600 words conceding the plan is wrong, then keeps the plan's wording

§1 carefully establishes that "most of them assumed a central scheduler or arbiter" is **false for 3 of 4 systems** (actors, contract-net, Linda). Then the "Honest verdict" paragraph concludes the plan "should keep both halves of its framing." This is the same pattern as S5(a): the review proves a plan claim is wrong, then advises keeping it because the *other* half of the sentence is right. If the scheduler half is false for 3 of 4 named systems, the plan should **fix the sentence** (e.g. "most made the per-unit intelligence small and fixed; blackboards additionally assumed a central scheduler"), not "keep it." A literature review that documents an error and then recommends preserving it is not serving the plan. Recommend: §1's verdict should call for a wording fix to the plan, not endorse the current wording.

## S9 (MODERATE) — citation hygiene: arXiv IDs, "Anonymous" authorship, unverifiable industry sources

- **arXiv:2603.28990 ("Drop the Hierarchy")** and **arXiv:2603.25928** — `2603` decodes as March 2026. Today is May 2026, so these are plausible. I verified 2603.28990 exists (author: Victoria Dochkina). But the references list it as **"Anonymous / 'Drop the Hierarchy and Roles' authors"** — this is wrong; the author is named on arXiv. Fix the reference. The review also says (coverage gaps) it is "a preprint not yet peer-reviewed" — fine, but the load-bearing 25,000-run number and the 5,006-roles number should be attributed to the named author.
- The review cites **CodeCRDT's "5–10% semantic conflict"** as "the load-bearing number" four times. I confirmed CodeCRDT exists (arXiv:2510.18893) and its third contribution is indeed "demonstration that LLM agents' stochastic behavior and semantic reasoning introduce failure modes (semantic conflict)." The specific "5–10%" and "up to 21% speedup / 39% slowdown / 600 trials" figures I could not verify line-by-line from the abstract alone. Given how load-bearing the 5–10% is to the conclusion, the review should either cite the exact table/section or move the number to the "not-fully-verified" appendix.
- Industry sources (Carvalho's Linda essay, Electric's Yjs post) are fine as cited, but the review leans on the Electric "AI agents as CRDT peers" piece as evidence the pattern is "already shipping." That is a blog post, not a deployment study; the review should not let a vendor blog carry "already shipping as a pattern" weight in §2.

---

# Block 2 — Structure

## ST1 (SUBSTANTIVE) — §8 and §9 are two grounding sections and there *is* redundancy; §8 is overlong

The task asked: do §8 and §9 earn their length? **§9 earns it; §8 does not, fully.** §9 (the four pm instances) is concrete, well-structured (today / living version / what it enables / prior-work cluster), and non-redundant — it is the best section in the document for the target audience. §8 (Claude Code feature-by-feature) is ~2,400 words and repeats one idea — "Claude Code has static config + reactive sessions and nothing in between, the plan is the missing middle" — across nine feature subsections. The "Relation / The hack / What the plan provides" template is applied nine times; by the fourth (Plugins) the reader has the point. The MCP and agentic-search subsections explicitly conclude "the plan adds nothing here" — those are honest but they are two subsections that exist to say "not applicable." **Recommendation:** cut §8 by ~40%. Keep CLAUDE.md, Subagents, Plan mode, and the agent-manager role as full subsections (those carry real contrast); compress Hooks/Skills/Plugins/MCP/agentic-search into a single short paragraph ("several other features — hooks, skills, plugins, MCP, agentic search — relate only weakly; the plan consumes them or packages around them"). The §8/§9 redundancy is specifically: both sections end on the *identical* "missing middle tier" sentence (§8 final para; §9 references it; conclusion (d) repeats it a third time). Say it once.

## ST2 (MODERATE) — the conclusion restates the whole document

The conclusion is ~1,500 words and re-walks (a) the old vision, (b) why it stalled, (c) what LLMs change, (d) the contribution, plus "close prior art," "honest read," and "coverage gaps." Sections (a)/(b)/(c) substantially repeat §§1–3 and the intro's "What surrounds the plan." A reader who read the body does not need the lineage re-listed. Recommend collapsing (a)+(b) into one short paragraph and letting (c)+(d) carry the conclusion.

## ST3 (MINOR) — duplicated header

Lines 340–341: **"### Coverage gaps in this review"** appears twice, consecutively. Delete one.

## ST4 (MINOR) — the intro "What the plan proposes" duplicates the plan

The intro spends ~500 words restating the plan's five claims. Some restatement orients the reader, but claims 1–5 are nearly verbatim the plan's own framing. Tighten — the review's job is to *survey the literature around* the plan, not re-summarize it at length.

---

# Block 3 — Non-expert accessibility (load-bearing)

The review is *better* than average here — it glosses many terms inline (PR, LLM, blackboard, CRDT, OT, tuple space, stigmergy all get a one-clause gloss). Credit where due. But several load-bearing terms slip through, and the audience (a PM / adjacent researcher evaluating whether the plan's bet is supported) will hit them.

## A1 — "non-deterministic" — used as a headline term, never glossed
It is in the contribution statement (intro, conclusion (d)) and is arguably the *most* important word in the document. The target reader does not know what it means in a data-structure context (and, per S6, it is technically shaky). **Gloss on first use:** "non-deterministic — meaning the artifact does not hold one settled value but several competing in-progress versions at once, the way a document with three unresolved suggested edits is not yet any single document."

## A2 — "operational transformation" / "causality preservation" / "convergence" (§2)
OT is glossed adequately. But "*its two guarantees — causality preservation and convergence*" drops two technical terms with no gloss. **Fix:** "its two guarantees — that edits are applied in an order respecting which edit came first (*causality preservation*), and that every copy ends up identical (*convergence*)."

## A3 — "state-based and operation-based variants" (§2, CRDT paragraph)
Dropped without gloss; the target reader cannot use this. Either gloss in one clause ("two flavors — one that syncs whole snapshots, one that syncs individual changes") or cut it; it is not load-bearing.

## A4 — "superposition" (used in intro term-gloss list? no — used in conclusion (d) and the plan)
"Holds proposals in superposition" — the review uses this physics metaphor in conclusion (d) without glossing. The target reader may or may not connect it to quantum superposition. **Fix:** "holds proposals in superposition — several candidate versions coexisting, none yet chosen."

## A5 — "strong eventual consistency" / "deterministic convergence" (§2, CodeCRDT bullet)
The CodeCRDT bullet quotes "deterministic convergence" and the conclusion mentions "guaranteed syntactic convergence." "Convergence" is used ~5 times and never glossed. Gloss on first use (§2): "convergence — the guarantee that all copies, however independently edited, end up identical."

## A6 — "voluntary self-abstention" (§5)
Glossed *parenthetically* ("an agent withdraws from a task outside its competence") — acceptable, keep.

## A7 — "TRL" — will appear if S1/S2 fixes are applied
When the review adds MAIF, do not import "TRL 7–8" without glossing ("Technology Readiness Level — a 1-to-9 maturity scale; 7–8 means a working system demonstrated in a real environment").

## A8 — "p<0.001 / Cohen's d=1.86" — if "Drop the Hierarchy" stats are cited
The review currently cites the 25,000-run / 44% / 14% numbers without statistical notation — good. If a revision adds p-values or effect sizes, gloss them or cut them; the target reader cannot use "Cohen's d."

## A9 — "Why should I care?" check on section openings
- §2 opens "*The plan's open questions ask, directly...*" — passes (tells the reader this section answers a plan question).
- §4 opens "*This is where the plan's prior art is most recent and most directly competitive.*" — passes, good hook.
- §6 opens "*The plan's 'Where this leads' section claims...*" — passes.
- **§1 opens** "*The plan's claim that prior coordination systems 'assumed a central scheduler or arbiter' deserves a careful, honest answer*" — borderline. The target reader does not yet know why the scheduler question matters. **Proposed opening:** "Before trusting the plan's claim to be 'a new kind of coordination,' a reader should know what the old kinds were — and whether the plan's one-sentence dismissal of them is fair. This section checks that."
- **§3 opens** "*The plan's artifact is 'a structured object ... text-renderable, that humans can audit.' That sentence sits downstream of a sixty-year lineage.*" — borderline; "sits downstream of a lineage" is writerly but doesn't tell the reader what they get. **Proposed:** "The idea of a document that is also a live, working thing is not new. This section traces it back sixty years, so the plan's 'living artifact' can be judged against what was already tried."

## A10 — undefined tool/research terms (quick list, each needs a one-clause gloss)
- "Yjs" (§2) — glossed once as "a popular CRDT library" — OK, keep.
- "SQLite" (§1 Linda paragraph) — unglossed; gloss as "a lightweight single-file database."
- "vector database" (§5 stigmergy) — unglossed; gloss as "a store that indexes data by meaning-similarity rather than exact match."
- "Monaco / React" — will appear if CodeCRDT internals are described; currently not, keep it that way.
- "operation classes" (§8 Skills, §9) — this is a plan-internal term; the review uses it as if defined. Gloss on first use: "operation classes — the named kinds of work a task can specialize into (e.g. 'reformat', 'coherence-check')."

---

# Block 4 — Prose

## P1 — emphasis density is too high
Bold and italics are used heavily — most paragraphs in §§1, 4, 5 carry 2–4 emphasised spans. By the conclusion the emphasis has stopped emphasising. Count per the methodology: roughly 6–10 emphasised spans per "page." **Recommendation:** reserve bold for the genuine load-bearing claim in each section (one per section) and the term being defined; cut the rest. Specifically, the conclusion bolds "*non-deterministic / relational / intelligence-resolved*" *and* re-bolds them in the body of (d) — pick one.

## P2 — recurring tic: "honest" / "honestly" / "the honest verdict"
"Honest" appears ~12 times ("the plan's honest framing," "honest verdict," "honest note," "honest confrontation," "honest read," "honest scoping," "Honest read on the framing"). It is a verbal tic and, worse, it is *self-congratulatory* — telling the reader the analysis is honest does not make it so. Cut to ~3 uses. "Honest verdict on the plan's framing" (§1 header) → "Assessing the plan's framing."

## P3 — em-dash overuse
The document uses em-dashes for drama throughout — often three or more per paragraph. Several sentences have two em-dash asides nested. E.g. intro: "*the last twelve months have produced LLM-agent systems that are strikingly close to the plan's architecture: decentralized multi-agent coordination over a shared state (CodeCRDT, 2025), AI agents as peers in a conflict-free replicated document (Yjs-based agent work, 2026)...*" — fine here, but elsewhere the dashes pile up. Convert half to commas, periods, or parentheses.

## P4 — "load-bearing" used as the review's own favorite adjective
"Load-bearing" appears ~6 times (the 5–10% number, §8, the methodology import). It is fine once or twice; it has become a crutch. Vary it.

## P5 — sentence-rhythm: §5's final paragraph is one long crescendo
The time-relativity rebuttal paragraph (§5 final) is ~200 words, mostly long compound sentences building to "*not 'cost-stratification is unsafe' but 'cost-stratification is correctly staged.'*" It reads as rhetoric rather than analysis (and per S5 the analysis underneath is shaky). Break it into shorter sentences and drop the rhetorical antithesis structure.

## P6 — "strikingly close" / "very close" / "strikingly" — intensifier creep
The review tells the reader prior work is "strikingly close" / "very close" / "very recent" repeatedly. Show the closeness with the comparison; cut the intensifier. (This tic is also why S1/S2/S3 matter — the review keeps *saying* things are close but the closest items, MAIF/MMP, were never found.)

---

# Step 5 — Citation-graph walk

**Seeds chosen (8), most load-bearing first:**
1. CodeCRDT (arXiv:2510.18893) — the review's single most-cited recent work.
2. SwarmSys (arXiv:2510.10047).
3. "Drop the Hierarchy and Roles" (arXiv:2603.28990).
4. CRDTs (Shapiro et al. 2011) — the §2 backbone.
5. Actor model (Hewitt 1973) / blackboard (Nii 1986) — the §1 backbone, walked forward for recent LLM-agent revivals.
6. MemGPT (arXiv:2310.08560) — §4's "artifact manages its own memory."
7. AutoGen (arXiv:2308.08155) — §4's central-arbiter confrontation.
8. Karpathy LLM-OS framing — §4.

**Method:** plain-topic web search + arXiv listing scan + abstract fetches, restricted to 2025–2026, with emphasis on the last ~6 months (the methodology's stated danger zone). Forward ("cited-by"/related) and backward (references/topic-neighbors) on each. Abstracts of the four most consequential hits fetched and verified verbatim.

**Coverage:** Good on the recent LLM-agent cluster (seeds 1–3, 6–8); thinner on classic-CS backward walk (seeds 4–5) — I did not pull the full reference lists of Shapiro 2011 or Nii 1986, because the review's *classic* coverage is already strong and the methodology flags recent work as the danger zone. The walk's payoff was entirely in 2025–2026 work, as predicted.

**New prior art found (not in the review):**

| Work | arXiv / venue | Relevance | Severity |
|---|---|---|---|
| **MAIF — Artifact-Centric Agentic Paradigm** | 2511.15097 (Nov 2025) | Preempts the headline "artifact-as-unit, data+intelligence fused, production" framing | **S1 — severe** |
| **Mesh Memory Protocol (MMP / CAT7)** | 2604.19540 (Apr 2026) | Typed shared-memory schema, semantic per-field merge of concurrent contributions, lineage DAG, role-weighted admission — preempts §2 + the "relational" and "intelligence-resolved" pillars; deployed | **S3 — severe** |
| **Semantic Consensus** | 2604.16339 (Apr 2026) | Formally names "Semantic Intent Divergence" = the plan's "integrity" problem; proposes detection+resolution | **S4 — substantive** |
| **TheBotCompany — Self-Organizing MAS for Continuous Software Dev** | 2603.25928 (Mar 2026) | Persistent multi-day software dev, specs-as-evolving-documents, real-tool eval — but central-arbiter (3 manager agents). Useful as a *contrast* point for §4/§9, and as another counterexample to "no academic close work is deployed" | moderate — should be cited |
| Agora "Protocol Documents" | (2024/25, surfaced in walk) | Agents autonomously negotiate/create protocols — relevant to §"Negotiation protocol" PR | minor — worth a footnote |

**Seeds that produced nothing new:** Actor model and blackboard backward walks produced no missed classic citation — the review's §1 classic coverage is solid (positive convergence signal for the historical half). MemGPT and AutoGen forward walks produced only the works already tabled above.

**Coverage verdict:** the walk found **two severe and two substantive misses**, all from the last ~6 months, all on the LLM-agent side — exactly the failure mode the methodology warns about ("the most damaging misses in our loops have all been from the last 6 months"). The review's recent-work coverage looked thorough but stopped at the three works the *plan* already named; it did not independently search for "artifact-centric agentic paradigm" or "multi-agent shared-memory data structure," which are the obvious queries for a review whose thesis is "a data structure for artifacts." This is the central deficiency of Cycle 1.

---

# Pressure-test answers (task item 4)

**Is "keep the framing" honest, or does it shade into overclaim?** It shades into overclaim in **three identifiable places**: (i) §1 — the review documents that "central scheduler" is false for 3 of 4 systems, then advises keeping the wording (S8); (ii) §5 — the review redefines "no central arbiter" to "no central adjudicator" to make the "Drop the Hierarchy" finding fit, then credits the *plan's existing* framing with surviving, when it is the review's *re-reading* that survives (S5a); (iii) the conclusion lists the EA claim among framings that "hold" when §6 showed it mostly doesn't (S7). The pattern: the review proves a plan claim is loose, then preserves it by supplying a better claim itself and attributing it to the plan. The correct move is to tell the plan to **change its wording** to the narrower version — not to certify the loose wording as surviving.

**Does the core contribution statement survive?** Partly. "An old vision newly enabled by LLMs" survives as *flavor*. "A new data structure — non-deterministic, relational, intelligence-resolved" does **not** survive as written: "non-deterministic" is the wrong word (S6); "relational" and "intelligence-resolved" are substantially preempted by MMP (S3). The residual that survives is narrower: *a negotiation-and-conflict layer for artifact-centric systems — multi-party concurrent proposals resolved by LLM reasoning against an integrity constraint, no central adjudicator* (see S1's proposed replacement).

**§8 vs §9 redundancy:** §9 earns its length; §8 does not — cut §8 ~40%, and stop repeating the "missing middle tier" line three times (ST1).

**The three close works — does the differentiation hold?** CodeCRDT: yes, the "corroborates not preempts" reading holds *on substance* (it really is code-merge-specific) — but the "not deployed" half of the differentiation is now undercut by MAIF/MMP being deployed (S2), so the review must differentiate on substance only. SwarmSys: holds — it genuinely stops at coordination. The Swarms/SwarmSys naming-collision note is good and correct, keep it. "Drop the Hierarchy": the characterization is **special-pleading in part** (S5a) — the paper is more of a challenge to pure self-organization than the review concedes.

**No-central-arbiter + cost-stratification + time-relativity rebuttal:** the rebuttal **partly hand-waves** (S5b) — the descending-floor premise is uncited and the rebuttal answers "is it safe?" while dodging "is it economical?". Downgrade from "correctly staged" to "an open risk with a plausible but unproven mitigation."

---

# Findings summary

**13 findings: 9 substantive, 4 phrasing/structure-minor.**
- Substantive: S1 (severe), S2 (severe), S3 (severe), S4, S5, S6, S7, S8, ST1.
- Minor/phrasing: S9 (citation hygiene — borderline substantive), ST2, ST3, ST4, plus the A-block (10 accessibility items) and P-block (6 prose items) which are real but individually small.

**Citation-graph walk coverage:** 8 seeds, 2025–2026 window emphasised. Walk found 4 missed works (MAIF, MMP, Semantic Consensus, TheBotCompany) — 2 severe, 1 substantive, 1 moderate — all from the last ~6 months. Classic-CS coverage verified sound (no misses on actor/blackboard/CRDT). The recent-LLM-agent coverage was the weak axis.

# Convergence assessment

**Not converged. The artifact needs significant work — this is a real Cycle-1 result, not a polish pass.** The prose, structure, and historical scholarship are good; the document is pleasant to read and intellectually careful in tone. But its *central job* — establishing whether the plan's bet is supported or preempted by prior work — is not done, because the citation walk it should have run was not run, and the two severe misses (MAIF, MMP) hit the headline contribution directly. The required next step is a **response cycle that runs the "narrow, don't collapse" procedure on MAIF and MMP**, rewrites the contribution statement to the residual (negotiation-and-conflict layer for artifact-centric systems, no central adjudicator), drops the now-false "no close work is deployed" differentiator, adds §2/§5 citations for MMP and Semantic Consensus, fixes the "non-deterministic" pillar word, and trims §8 and the conclusion. After that, a Cycle 2 reviewer should re-walk forward from MAIF/MMP specifically, since that is the sub-literature the plan actually lives in and it is moving fast.

---

# Appendix — what the draft-feedback round established (read after the review was drafted)

Per the task, I scanned `REVIEW_RESPONSE_LIVING_ARTIFACTS_DRAFT1.md` and its addendum *after* drafting the above. This appendix records what that round already settled and where my Cycle-1 findings collide with it.

**What the draft round settled (and I do not re-litigate):**
- §9 ("instances grounded in pm") exists because of the addendum's items 8–10. It is a deliberate, plan-owner-requested section. My ST1 stands (§9 earns its length; §8 does not) — that is consistent with the addendum, which itself distinguishes the two groundings.
- The Swarms/SwarmSys naming-collision note (Decision 1) is deliberate and correct — keep it.
- The EA-direction concession (Decision 3) is deliberate. My S7 is not "the review failed to concede" — §6 *does* concede; S7 is narrower: the *conclusion* contradicts §6's concession by listing EA among framings that "hold."
- The CodeCRDT-as-supporting-evidence reframe (Decision 5) is deliberate. I do not dispute it; CodeCRDT genuinely corroborates.

**Where my Cycle-1 findings directly collide with the draft round's standing guidance — and why the guidance must now yield:**
- The draft round's **Decision 1** ("keep the whole framing; the close prior art is academic, not deployed") is the single instruction my walk most directly invalidates. The decision's load-bearing premise is *"keep the plan's framing unless the close-prior-art works saw commercial or other real-world success."* MAIF claims TRL 7–8 production; MMP claims production deployment with an Anthropic-directory plugin. The premise's own escape clause is now triggered. The standing guidance "keep the framing" was reasonable *given the three works the draft round knew about* — it is not reasonable given MAIF/MMP. This is not a reason to override the "narrow, don't collapse" principle; it is the principle finally having something to bite (S1/S2/S3).
- The draft round explicitly says (Decision 4) the contribution is "*larger* and more defensible than the first draft's narrowed version" and the first draft "narrowed too aggressively." My finding is the opposite: the first draft's narrowing instinct was *correct*, and Decision 4 walked it back on the strength of a prior-art survey that had not yet found MAIF/MMP. Decision 4's larger contribution claim ("a new data structure ... an old vision newly buildable") is the claim S1/S3/S6 show does not survive. The contribution should narrow again — to the residual in S1 (a negotiation-and-conflict layer for artifact-centric systems).
- The draft round's **Decision 2** (time-relativity rebuttal) is the origin of the §5 rebuttal my S5b flags as partly hand-waving. The plan owner's phrasing — "whatever their strong model was will be weak within a few years" — is asserted in the response with no citation, and the lit review inherited that. S5b stands: the rebuttal needs a citation for the descending-floor premise and must concede the economic (not just safety) question.

**Net:** the draft-feedback round was a pre-cycle calibration done before any citation walk. Its central instruction ("keep the framing") was conditional on a premise the walk has now falsified. Cycle 1's job is precisely to surface that — the loop is working as designed.
