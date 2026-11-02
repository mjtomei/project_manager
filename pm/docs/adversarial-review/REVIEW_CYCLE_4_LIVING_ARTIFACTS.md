# Review Cycle 4 — Literature Review: Living Artifacts

**Artifact:** `pm/docs/literature-review-living-artifacts.md` (~15,970 words)
**Reviewer:** fresh adversarial pass, blind to prior cycles at drafting time
**Date:** 2026-05-15
**Methodology:** four blocks (substance / structure / accessibility / prose), step-5 citation-graph walk both directions, "narrow the contribution; don't collapse it"

---

## Headline assessment

This is a careful, honest document. The contribution is narrowed not collapsed, the prior-art comparisons are mostly point-by-point, and the closest works (MMP, CodeCRDT, AgentNet, ScienceClaw) are treated with the right structure: what they do, what they preempt, what the plan's residual is. The prior cycles clearly did their job — there is little loose overclaiming left.

But it is not converged, for two reasons.

First, **the citation-graph walk found three genuinely close 2026 papers the review does not cite**, one of them (autopoietic architectures / Ψ-Arch, arXiv:2604.13934) naming the *exact scientific concept* — autopoiesis — that the plan's whole "self-maintenance" idea is, and one of them (arXiv:2605.12087) carrying the literal phrase "intermediate artifacts as first-class citizens," which collides head-on with the review's load-bearing "unsettled state as first-class" contribution sentence. The frontier moved again. A Cycle-3 walk a year ago would not have found these; a Cycle-4 walk in May 2026 must.

Second, **the accessibility block surfaces a real and structural problem**: the new ~400-word executive summary is better than the body but still leans on un-glossed phrasing, and the document as a whole is *far too long for its stated audience*. A non-developer evaluating whether the plan's bet is supported will not read 16,000 words. The review has grown each cycle — that is the wrong direction for a Block-3-load-bearing artifact.

**Findings: 24 total — 9 substantive, 15 phrasing/accessibility/structure.**

This is fewer substantive findings than Cycle 3 reportedly produced, and the phrasing findings are getting closer to nitpicks. But the three uncited papers are not nitpicks, and the length problem is structural. **Verdict: one more cycle needed** — a short one, focused on (a) integrating the three walk finds, (b) cutting the document by a third, and (c) tightening the exec summary. After that, converged.

---

# Block 1 — Substance

## S1 (SUBSTANTIVE) — Autopoiesis is the precise name for the plan's central concept, and neither the plan nor the review uses it

The citation walk's most important find. **"Towards Enabling An Artificial Self-Construction Software Life-cycle via Autopoietic Architectures"** (arXiv:2604.13934, April 2026) is uncited.

Verbatim from the abstract:

> "Software engineering research has focused on automating maintenance and evolution processes... The emergence of foundation models (FMs) with strong code understanding and reasoning abilities offers new opportunities for autonomous software behavior. Inspired by Artificial Life (ALife), we propose a fundamental shift in the Software Development Life-Cycle (SDLC) by introducing self-construction mechanisms that enable software to evolve and maintain autonomously."

The paper defines **autopoiesis** as "a process by which systems continuously regenerate and sustain their components and connections autonomously" and proposes Ψ-Arch, a six-component architecture (original software, instruction tape, constructor, copy machine, control machine, and a foundation-model reasoning unit) whose reasoning unit does causal reasoning under Pearl's framework.

**What the prior art does:** proposes that software *self-constructs and self-maintains* at runtime — identifies dead code, refactors itself, generates improved replicas — driven by a foundation-model reasoning unit, explicitly grounded in the biological concept of autopoiesis and in Artificial Life.

**What the artifact claims:** the plan's headline novelty is "agency — goals, negotiation, *self-repair* — in the file itself," with artifacts that "spawn their own maintenance tasks." The review's §3 (living-document vision) and §9 Instance 1/2 ("self-maintenance task the plan artifact spawns from its own wants") are exactly the self-maintenance idea autopoiesis names.

**Intersection (what is preempted):** the concept "software that continuously regenerates and sustains itself, driven by an FM reasoning unit" is now published under its proper scientific name. The plan's word "self-maintenance" is a folk term for autopoiesis. The review currently traces the "living document" lineage to Engelbart, Victor, Knuth — all *human-facing* augmentation — and misses that there is a *2026* paper doing autonomous software self-maintenance with an FM, which is far closer.

**Residual contribution (proposed):** Ψ-Arch is single-system and architecture-level — one program that rewrites itself; its unit is the codebase, it has no concurrency story, no peer-to-peer negotiation between artifacts, no in-flight unsettled state held as first-class, no task lifecycle, and no multi-artifact integrity constraint. The plan's residual: autopoiesis applied not to one self-rewriting program but to a *population of artifacts that negotiate their self-maintenance with each other* through a shared substrate.

**Proposed edit:** §3 should add an autopoiesis subsection (autopoiesis = Maturana & Varela's 1972/1980 concept of a system that continuously produces and sustains itself; the plan's "self-maintenance" is autopoiesis at the artifact level). Cite arXiv:2604.13934 as the closest *self-construction* prior art. The conclusion's "an old vision, newly buildable" gains force from naming the biological lineage. And the plan's text should adopt the word "autopoietic" — it is the precise term, the way §5 told the plan to adopt "stigmergy."

## S2 (SUBSTANTIVE) — "Intermediate Artifacts as First-Class Citizens" collides with the review's load-bearing contribution sentence

**"Intermediate Artifacts as First-Class Citizens: A Data Model for Durable Intermediate Artifacts in Agentic Systems"** (arXiv:2605.12087, May 2026) is uncited.

Verbatim from the abstract:

> "Many AI systems are organized around loops in which models reason, call tools, observe results, and continue until a task is complete... We argue that such systems should preserve durable, inspectable intermediate artifacts: typed, structured, addressable, versioned, dependency-aware, authoritative, and consumable by downstream computation."

**What the prior art does:** proposes a systems-level data model for intermediate work products (evidence maps, assumptions, plans) as "typed, structured, addressable, versioned, dependency-aware, authoritative" persistent entities, with additive/superseding update semantics and lineage. Passive durable data — no agency.

**What the artifact claims:** the review's conclusion §(d) states the contribution as a data structure that holds "unsettled state as first-class... proposals in flight, not just committed content" and is "relational." The literal phrase "first-class citizens" + "typed, dependency-aware, versioned" + "intermediate artifacts" is now a published data-model paper, one month old.

**Intersection:** the data-model framing — typed, versioned, dependency-aware, relational, lineage-carrying intermediate artifacts as first-class — is preempted as a *data model*. The review's §(d) "Relational" bullet ("negotiation history, cross-artifact references, want-dependencies") is substantially what 2605.12087 calls "dependency-aware" with lineage.

**Residual:** 2605.12087 is a *passive* data model — artifacts are inspectable and revisable by humans/agents, they do not act, negotiate, or carry wants. The plan's residual over it is exactly the agency layer, *and the specific representation of unsettled in-flight state mid-negotiation* (2605.12087's "intermediate artifacts" are completed sub-products like evidence maps, not proposals-in-superposition). But the review can no longer present "typed, dependency-aware, first-class intermediate artifacts" as part of its own contribution vocabulary unchallenged.

**Proposed edit:** cite arXiv:2605.12087 in §4 or §8 as the closest *data-model* prior art for first-class intermediate artifacts. Revise conclusion §(d): the contribution is not "unsettled state as first-class" *as a data model* (that exists) — it is *agency over* that data model, plus the specific representation of proposals in superposition (a stronger claim than "durable intermediate artifacts").

## S3 (SUBSTANTIVE) — "Loosely-Structured Software" has endogenous evolution — artifacts the system rewrites itself

**"Loosely-Structured Software: Engineering Context, Structure, and Evolution Entropy in Runtime-Rewired Multi-Agent Systems"** (arXiv:2603.15690, March 2026) is uncited.

Verbatim from the abstract:

> "As LLM-based multi-agent systems (MAS) become more autonomous, their free-form interactions increasingly dominate system behavior. However, scaling the number of agents often amplifies context pressure, coordination errors, and system drift."

The paper proposes three properties: View-Constructed Programming, Runtime Semantic Binding, and **Endogenous Evolution** — "the system's behavior-shaping files (artifacts) are rewritable by the system itself, enabling self-improvement," framing artifacts as "the system's hard drive" of prompts, skills, plans, memories that agents "programmatically read, analyze, and rewrite."

**What the prior art does:** a paradigm where the artifacts shaping system behavior are self-rewritten by the system; explicitly names coordination errors and "system drift" — the same coherence-under-concurrency problem §5's Semantic Consensus names.

**Intersection:** "Endogenous Evolution" preempts the bare claim "artifacts that rewrite themselves." The plan's Instance 1/2 (plan and PR artifacts that self-maintain) is an instance of endogenous evolution.

**Residual:** LSS's artifacts are passive files an *agent* rewrites — the agency sits in the agents, the artifacts are the "hard drive." The plan puts agency *in the artifact* (it carries wants, spawns its own maintenance, is itself a negotiating peer). Same intersection-and-residual structure as MAIF and ScienceClaw — but LSS is closer than either on the *self-rewriting* axis and must be cited.

**Proposed edit:** add to §4 or §8 alongside MAIF/ScienceClaw with the standard one-paragraph what-it-does / residual treatment.

## S4 (SUBSTANTIVE) — The convergence-of-negotiation gap is named as a risk but the plan has no mechanism beyond timeout

§5 "Does the negotiation converge?" and the coverage-gaps list both honestly flag that LLM-to-LLM proposal negotiation termination is unestablished. Good. But the review stops at "the timeout-into-dropped rule is the right kind of safeguard." That under-delivers. The review should, per Block 1 ("what additional validation should be done"), name the *concrete experiment*: run N artifact-pairs through forced-conflict negotiations, measure termination rate, oscillation rate, and false-consensus rate, against the timeout. The §7 verdict does name a cheap experiment for the "wants" scaffold — §5 should do the same for convergence. As written, the biggest empirical risk in the plan is flagged but not made actionable.

## S5 (SUBSTANTIVE) — The cost-stratification "bet" discussion is the longest in the review and is over-argued

§5's cost-stratification passage (the "bet"/"hedge" treatment of the strong-model-privilege finding) runs ~600 words and circles the same point three times: cheap models may not negotiate well; the curve is moving; watchers are the safety net but not the economics net. This is *correct* but it is over-argued — the review spends more words hedging this one secondary claim than it spends on the entire §6 evolutionary-computation analysis. Block 1 asks for proportionality. Recommend cutting this to ~250 words: state the threshold finding, state the bet, state the one honest residual (benchmark-to-negotiation transfer), name the watcher fallback, stop. The "one caution on using this study for both sides" paragraph is a caution on a caution — cut it or fold one clause into the main hedge.

## S6 (SUBSTANTIVE) — §6's "negotiated internal selection" sliver may itself be partly preempted

§6 lands the evolutionary claim on one residual: "selection emerging from peer-to-peer negotiation among the candidates themselves." The review checked A-Evolve, Promptbreeder, FunSearch, AlphaEvolve, ADAS. It did not check whether *quality-diversity* / *open-ended* evolution work (MAP-Elites lineage, and recent LLM-driven open-ended systems like OMNI or the 2025 "open-ended" agent papers) has candidates that influence each other's selection pressure via niche competition. MAP-Elites already has candidates competing *locally within niches* rather than against a single global fitness — which is closer to "negotiated selection" than the review's framing admits. Recommend the response cycle verify this; if niche-local competition preempts part of the sliver, the residual narrows further to "candidates that *reason about and argue* their own survival," not merely "local rather than global selection."

## S7 (SUBSTANTIVE) — The MMP "production" claim is hedged correctly but the review never says whether MMP's CAT7 schema is a *good* answer

§(d) and §2 both note MMP's CAT7 seven-field schema is "one point in that design space, not the answer." Fair. But the review never engages whether a *fixed* seven-field schema is the right shape for the plan's artifact at all. The plan's artifact must hold proposals-in-superposition, negotiation history, want-dependencies, task lifecycle state — that is plausibly *not* expressible in a fixed-field schema. The review should say so: a fixed schema (MMP, MAIF's MAIF format) is a positive design choice for *typed knowledge* but likely wrong for *unsettled work state*, which argues for a more open representation. This is a substantive design-relevant observation the review currently leaves on the table.

## S8 (SUBSTANTIVE) — No empirical contradiction is surfaced for the "human as boundary" claim

Block 1 asks: "what empirical data contradicts the key points." The review does this well for "no central arbiter" (the "Drop the Hierarchy" hybrid finding). It does *not* do it for "the human becomes a boundary, not a bottleneck." There is a real tension: the "Drop the Hierarchy" weak-model finding implies that if cheap-tier negotiation degrades, *humans get pulled back in* — the boundary expands. And the multi-agent-failure-rate literature (41–86.7%) implies humans may need to intervene far more than "boundary, not bottleneck" suggests. The review should add one paragraph: the boundary claim is in tension with measured multi-agent failure rates, and the honest framing is "human-at-boundary is the *goal state*, reached as integrity-maintenance matures — not a property the substrate has on day one."

## S9 (SUBSTANTIVE) — §7's proposed experiment is under-specified as a control

§7's verdict proposes "the same artifact through a 'wants'-framed prompt and through a plain instruction-framed prompt." Good direction, but as a controlled experiment it lacks a dependent measure. Per Block 1 ("missing parameters"): the experiment needs a stated DV — e.g., number and quality of self-maintenance tasks generated, rated by a blind human or a held-out judge, on a fixed set of artifacts with known coherence defects. Without a DV the "cheap controlled comparison" is not yet a protocol. Recommend §7 name it.

---

# Block 2 — Structure and readability

## ST1 (STRUCTURE) — The review is too long and has grown every cycle

~15,970 words. For a Block-3-load-bearing artifact whose audience is a non-developer deciding whether the bet is supported, this is roughly three times too long. The exec summary plus §1's framing plus the conclusion already deliver the full verdict; §§1–8 are evidence a motivated reader consults selectively. Recommend an explicit restructure: keep the exec summary, the conclusion, and a *much shorter* §9 (the concrete pm instances — the part a decision-maker actually needs) in the main body; move §§1–7's detailed prior-art surveys into a clearly-labelled "Appendix B — prior-art survey" the way Appendix A already holds the Claude Code walk. The non-developer reads 4,000 words; the specialist reads the appendix. Growing the document each cycle is the wrong direction.

## ST2 (STRUCTURE) — §§4 and 5 overlap heavily on the central-coordinator argument

§4's "AutoGen/MetaGPT/ChatDev — central-coordinator confrontation" and §5's "self-organizing LLM agents" both make the same move: mainstream is orchestrator-centric, a research frontier is decentralized, the plan's residual is the artifact substrate. AgentNet is discussed in *both*. Recommend merging: §4 ends with the central-coordinator foils; §5 owns *all* the decentralized-frontier papers (AgentNet, SwarmSys, Drop-the-Hierarchy, Agora-Opt) in one place. Currently the reader meets AgentNet twice.

## ST3 (STRUCTURE) — The conclusion repeats the body almost section-for-section

The conclusion's "the other close prior art points the same way" paragraph re-summarizes CodeCRDT, SwarmSys, Drop-the-Hierarchy, MAIF, TheBotCompany, Swarms — each already covered at length. A conclusion should *synthesize*, not re-list. Recommend cutting this paragraph to two sentences: "Every close prior-art work surveyed corroborates the plan's direction on a narrower slice; none builds the general self-maintaining artifact substrate. That layer is the plan's job."

## ST4 (STRUCTURE) — "Read on the framing" and "Coverage gaps" are both good and both buried

The conclusion's "Read on the framing" (the four calibrations) and "Coverage gaps in this review" are the two most useful sections for a decision-maker — they say exactly what is solid and what is not. They are at the very end of a 16,000-word document. Recommend promoting a compressed version of both into the executive summary, or immediately after it.

## ST5 (STRUCTURE) — §9 should come earlier

§9 ("the plan's instances, grounded in pm") is the most concrete and most decision-relevant section — it is what the plan actually builds. It sits at position 9 of 9, after eight sections of prior-art survey. A reader deciding whether to back the plan wants §9 *early*. Recommend moving it to position 2, right after the introduction: here is what gets built, then here is the prior art it sits in.

---

# Block 3 — Non-expert accessibility (load-bearing)

## A1 (ACCESSIBILITY) — The new executive summary is better than the body but still leans on un-glossed phrasing

Assessment of the ~400-word exec summary against the non-developer test:

What works: "building software files that are not passive documents but active participants that argue out their own changes" is genuinely accessible. The one-line verdicts on AgentNet/ScienceClaw/MMP are concrete.

What fails:
- "the contribution narrowed" — "contribution" and "narrowed" are review-craft jargon. A non-developer does not know a literature review has a "contribution" or what "narrowing" one means. Replace: "yes — though the plan should claim *less* as brand-new than it might want to."
- "**ScienceClaw + Infinite (2026)** built a layer that automatically prunes a tangle of conflicting research outputs" — "prunes," "layer," and "research outputs" are all unglossed. Replace: "built a system that automatically cleans up when automated research tools produce contradictory or duplicated results."
- "its files are passive records; the plan's files have their own goals" — "passive records" is fine; good.
- "as a general substrate inside a working tool" — "substrate" appears in the exec summary unglossed. This is the single most-repeated jargon word in the whole document (it appears dozens of times) and a non-developer does not know it. Replace throughout the exec summary with "foundation" or "the underlying machinery." Gloss it once on first use in the body: "substrate — the common underlying machinery everything else is built on."
- "The eight sections below are the evidence; read on only if you want it." — good, keep.

Verdict on the exec summary: it serves a non-developer about 70% of the way. Three words — contribution, prune, substrate — break the spell. Fixing those three makes it actually work.

## A2 (ACCESSIBILITY) — "substrate" is used ~40 times and never glossed

The single worst jargon offender. "Substrate" is the load-bearing noun of the whole document (the contribution is "a general self-maintaining artifact substrate") and it is never defined. A non-developer reads it as a chemistry or biology word. Gloss on first use (introduction): "the *substrate* — the shared underlying machinery that every artifact is built on and runs through." Then it can be used freely.

## A3 (ACCESSIBILITY) — "DAG" is glossed but the gloss introduces new jargon

§5 AgentNet: "a dynamically restructured DAG (a directed acyclic graph — a structure of steps where each depends on earlier ones and nothing loops back)." The gloss is decent but "directed" and "acyclic" are themselves jargon a non-developer skims past. Tighten: "a DAG — a chart of steps where each step depends on earlier ones, with no step ever circling back to repeat." Same gloss appears for ScienceClaw — make sure it is glossed once and cross-referenced, not re-glossed differently.

## A4 (ACCESSIBILITY) — "operational transformation" / "CRDT" section opens with the mechanism, not the benefit

§2 opens "Can many edits happen to one document at the same time without a referee deciding the order?" — actually that *is* a good benefit-first opening, keep it. But within the section, "operational transformation" and "conflict-free replicated data type" are each given a full mechanical gloss before the reader knows why they should care. The "Why should I care?" check: the reader needs to know up front "this part of the plan carries no risk because the problem was solved decades ago" — which the section *does* say, but only at the end ("the plan's concurrency substrate is not a research risk"). Move that sentence to the section opening.

## A5 (ACCESSIBILITY) — "stigmergy" is glossed well; "blackboard" is not glossed on its load-bearing reuse

§1 glosses "blackboard system" properly on first use. But §8 and the conclusion use "blackboard" as a bare noun ("the plan's *artifact* is a blackboard"). A non-developer who skipped §1 has no anchor. Either cross-reference ("a blackboard — the shared workspace of §1") or re-gloss in five words.

## A6 (ACCESSIBILITY) — "superposition" is a physics word used metaphorically without enough scaffolding

The introduction glosses "superposition" as "many possible versions of the document held at once, none yet the final one." That gloss is fine. But the word recurs (§5, conclusion §d) and each time it risks reading as physics mysticism. Recommend: after the first gloss, prefer the plain phrase "multiple competing versions held at once" and reserve "superposition" for at most one memorable use. A non-developer does not gain anything from the physics borrow.

## A7 (ACCESSIBILITY) — §7 opens well; "persona prompting" is a name-drop without the three-part explanation

§7 uses "persona prompting," "expert persona," "object personas" — the Block-3 rule is every named method gets "what it is, why we mention it." "Persona prompting" gets a working gloss ("telling the model to reason as a particular kind of entity"). "Object personas in design and social simulation" does not — it is named and dropped. Either explain it in one clause ("object personas — treating a non-human thing, like a product, as a character with preferences, a technique used in design research") or cut it.

## A8 (ACCESSIBILITY) — "non-deterministic" is flagged in the conclusion as imprecise but the fix is left to "the plan owner"

Conclusion §(d) says the plan's word "non-deterministic" is imprecise and "the plan owner may want to replace it." Block 3 says *propose the fix*. The review already has the replacement ("unsettled-state-as-first-class") — so state it as a direct recommendation, not a deferred suggestion. Drop "may want to."

## A9 (ACCESSIBILITY) — "RAG" appears once, expanded but unexplained

§5/walk: "Retrieval-Augmented Generation (RAG)-based framework." Expanding the acronym is not glossing it. A non-developer does not know what retrieval-augmented generation *is*. One clause: "RAG — a technique where the model looks up relevant documents and feeds them to itself before answering." Or, since it is only incidental to AgentNet's description, cut it.

---

# Block 4 — Writing quality and prose craft

## P1 (PROSE) — "narrowed but intact" / "relocated, not eliminated" repetition

These two phrases are load-bearing and earned, but they appear so often (the "relocated not eliminated" idea recurs in §4, §5 twice, §9 Instance 3, conclusion §d, and "Read on the framing") that they have become a tic. Recommend: state the relocation argument *once* fully (§5 is the right home), and elsewhere refer back ("the relocation argument of §5") rather than re-stating it. Counted roughly six full re-statements; three would do.

## P2 (PROSE) — em-dash overuse

Emphasis-density check: many sentences carry two or three em-dashes. Example, §1 actor model: "not 'actors had a central scheduler' (they didn't) but 'actors' per-unit behavior was a static program; ours is a general reasoner.'" Several sentences use the dash as the default connector. Recommend a copy-edit pass converting roughly half the em-dashes to commas, periods, or parentheses. Used densely they stop emphasizing.

## P3 (PROSE) — buried main clauses in long sentences

§4 AgentNet sentence: "Two things keep the plan's claim a genuine departure even so." then a long follow-on. And the conclusion's MMP "Stated as the plan's contribution" italic block is a single ~120-word sentence-pile. Block 4: the load-bearing claim should be the main clause. Recommend breaking the MMP italic block into three sentences: (1) MMP solves cross-session knowledge sharing. (2) So the plan is not the first typed cross-session shared memory. (3) But MMP has no task concept — the plan's subject is work coordination, which MMP omits.

## P4 (PROSE) — "Stated precisely" / "Stated plainly" / "Stated as" tic

The phrase "stated [precisely/plainly/as the plan's contribution]" appears at least eight times as a paragraph-pivot. It is a verbal crutch. Vary or cut: often the sentence after it can simply be the sentence.

## P5 (PROSE) — hedge stacking in the coverage-gaps and §5 passages

§5: "may be measured on different task distributions... If so... the 95% figure is weaker bull-case evidence than it looks." Three hedges in two sentences on a point already hedged in the prior paragraph. Pick the one real uncertainty (benchmark-to-negotiation transfer) and state it once with confidence: "The 95% figure measures benchmark quality, not negotiation competence — treat it as suggestive, not as evidence the routine tier is ready."

## P6 (PROSE) — "genuine" / "genuinely" overused

"genuine departure," "genuinely new," "genuinely open," "genuinely close," "genuinely decentralized" — the word appears ~12 times. It is doing emphasis work that the surrounding argument should do. Cut most; where the contrast is real, the sentence shows it without the adjective.

---

# Citation graph walk

**Walk date:** 2026-05-15. **Walker:** fresh session, blind to prior cycles at walk time.
**Tooling:** WebSearch (Google-backed) + WebFetch on arXiv abstract pages. Date emphasis: last 12 months, with specific attention to Feb–May 2026.

## Seeds

| # | Seed | Direction walked | Result |
|---|------|-----------------|--------|
| 1 | AgentNet (arXiv:2504.00587) | forward (cited-by) + sibling search | Surfaced **arXiv:2603.15690 (Loosely-Structured Software)** and confirmed AgentNet/Drop-the-Hierarchy cluster is current. |
| 2 | MAIF (arXiv:2511.15097) | forward + topic search "artifact-centric paradigm 2026" | Surfaced **arXiv:2605.12087 (Intermediate Artifacts as First-Class Citizens)** — May 2026, directly on-topic. |
| 3 | "Drop the Hierarchy" (arXiv:2603.28990) | forward + topic "self-organizing LLM agents 2026" | No new uncited paper; confirms cluster (AgentNet, AgentsNet, TheBotCompany already cited). |
| 4 | CodeCRDT (arXiv:2510.18893) | forward + topic "CRDT semantic conflict LLM 2026" | No new uncited paper; Electric/Yjs and Semantic Consensus already cited. Confirmed CodeCRDT's 5–10% figure characterization is accurate ("preliminary inspection suggests 5–10% semantic conflicts"). |
| 5 | Externalization survey (arXiv:2604.08224) / InfiAgent | forward + topic "self-maintaining artifact software 2026" | Surfaced **arXiv:2604.13934 (Autopoietic Architectures / Ψ-Arch)** — April 2026, the closest *self-construction* prior art; also noted arXiv:2605.07717 "AI-Native Large-Scale Agile Manifesto" (a manifesto, lower priority) and arXiv:2602.02235 / 2602.10046 (agentic *artifact evaluation* — different sense of "artifact," not relevant). |
| 6 | Persona-prompting cluster (Salewski 2023) | forward + topic "object persona / anthropomorphize non-agent" | No direct study of "anthropomorphize a non-agent artifact as having wants." Confirms §7's stated coverage gap is real. Anthropic's "Persona Selection Model" (alignment.anthropic.com, 2026) is about the *Assistant* persona, not object personas — not a miss. |
| 7 | Promptbreeder / A-Evolve (arXiv:2602.00359) | forward + topic "negotiated selection evolutionary LLM" | No paper doing peer-negotiated selection; §6's residual sliver holds. *Open item:* MAP-Elites / quality-diversity niche-local competition not checked — flagged as S6. |

**Coverage:** 7 seeds, both directions, ~120–150 titles/abstracts scanned, date window emphasis Feb–May 2026. **Three uncited papers found** (2604.13934, 2605.12087, 2603.15690), all from the last ~3 months — exactly the recent-accumulation pattern the methodology predicts. Two coverage gaps confirmed as genuine (object-persona; negotiated selection). One new open item raised (quality-diversity, S6).

This walk matched the prior cycle's standard (Cycle 3 found three uncited ~1-year-old papers; this walk found three uncited ~3-month-old papers).

## Additions proposed

1. **arXiv:2604.13934 (Autopoietic Architectures / Ψ-Arch)** — cite in §3 and the conclusion as the closest self-construction prior art; adopt the word "autopoiesis." See S1.
2. **arXiv:2605.12087 (Intermediate Artifacts as First-Class Citizens)** — cite in §4/§8; revise conclusion §(d). See S2.
3. **arXiv:2603.15690 (Loosely-Structured Software)** — cite in §4/§8 alongside MAIF. See S3.

---

# Convergence assessment

**Verdict: one more cycle needed — a short, targeted one.**

The phrasing findings (Block 4, most of Block 3) *are* getting pedantic — em-dashes, "genuine," "stated precisely." That is a converged signal for prose. If the only findings were Blocks 3–4, this review would call convergence.

But two things block convergence:

1. **Three uncited 2026 papers**, one (autopoiesis) naming the plan's central concept by its proper scientific name. That is substantive and the methodology's whole point is that the frontier keeps moving. It must be integrated.
2. **The length problem is structural, not cosmetic.** A 16,000-word document fails its load-bearing Block-3 obligation regardless of how good each sentence is. The review has grown every cycle. The next cycle must *cut*, not add — restructure §§1–7 into an appendix and the document drops to ~5,000 readable words.

After the next cycle integrates the three papers and cuts the length, this is converged. There is no fourth substantive theme waiting — the prior-art story is now well-mapped, the contribution is correctly narrowed, the calibrations are honest. The remaining work is integration and compression, not discovery.

**What the findings point toward next:** (a) add the three papers with the standard intersection/residual treatment; (b) adopt the word "autopoiesis" in the plan itself; (c) cut the document by ~two-thirds via appendix restructure; (d) tighten the exec summary's three broken words (contribution, prune, substrate); (e) make the §5 convergence risk and §7 wants-experiment into named protocols with stated dependent measures.

---

# Appendix — what prior cycles missed

After drafting the above, I scanned `REVIEW_CYCLE_1/2/3_LIVING_ARTIFACTS.md`, their responses, and the draft addenda.

- **Prior cycles caught AgentNet, MMP, Semantic Consensus, Agora-Opt, A-Evolve, the Externalization survey, ScienceClaw, Agent-Native Research Artifacts** — a strong walk record. Cycle 3 explicitly found "three uncited ~1-year-old papers." The walk discipline is working.
- **What they missed:** none of the three cycles surfaced the word **autopoiesis** or the autopoietic-architectures paper (2604.13934). This is the more interesting miss — it is not just an uncited paper, it is an uncited *concept*. Every cycle reviewed the "self-maintenance" claim and none flagged that self-maintenance has a 50-year-old scientific name (Maturana & Varela) and a fresh 2026 software paper. The reviewers were walking the *multi-agent-coordination* citation neighborhood thoroughly and the *artificial-life / autopoiesis* neighborhood not at all. That is a seed-selection blind spot: all prior seeds were coordination/agent papers; none was a self-organization-of-systems paper.
- **2605.12087 and 2603.15690** are both genuinely new (March/May 2026) — a fair miss for earlier cycles, not a failure; this is the recent-accumulation the methodology expects.
- **The length problem:** prior cycles flagged length (Cycle 3's headline says "the review is *long*") but every response *added* material. No cycle treated length as load-bearing enough to force a cut. The document grew from ~14,267 words (Cycle 3) to ~15,970 now. Prior cycles diagnosed the symptom and the responses made it worse. This is the clearest process failure across the loop: an accessibility-load-bearing artifact cannot grow every cycle.
