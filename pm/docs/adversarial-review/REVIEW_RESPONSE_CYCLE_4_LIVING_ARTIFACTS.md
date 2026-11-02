# Review Response — Cycle 4: Literature Review, Living Artifacts

**Artifact:** `pm/docs/literature-review-living-artifacts.md` (~15,970 words at Cycle 4 start)
**Responds to:** `REVIEW_CYCLE_4_LIVING_ARTIFACTS.md`
**Date:** 2026-05-15

---

## Process constraint for this cycle (binding on the apply agent)

Every prior cycle flagged length; every prior response *added* material. The
document grew ~14,267 → ~15,970 words while its load-bearing Block-3
obligation (readable by a non-developer) degraded. **This cycle's apply pass
must net negative.** Each ADD below is paired with a larger CUT. The running
net-words estimate at the end of each edit must trend down. Target: well under
15,970, ideally near ~12,000. If the apply agent finishes with a positive net,
the pass has failed and must be revised before commit.

The structural lever is Edit 1: move the §§1–7 prior-work survey *detail* into
a new **Appendix B**, leaving a lean, non-developer-navigable body. That single
move does most of the cut; the rest is trimming.

---

## Part 1 — Verification of the three uncited papers

All three arXiv IDs resolve to real papers. Abstracts fetched from arXiv and
quoted verbatim below. None is unverifiable; none is hallucinated.

### Paper A — arXiv:2604.13934, Ψ-Arch / Autopoietic Architectures

"Towards Enabling An Artificial Self-Construction Software Life-cycle via
Autopoietic Architectures" — Rodriguez-Cardenas, Nader Palacio, Poshyvanyk.

Verbatim abstract: *"...we propose a fundamental shift in the Software
Development Life-Cycle (SDLC) by introducing self-construction mechanisms that
enable software to evolve and maintain autonomously. This position paper
explores the potential of Autopoietic Architectures, specifically Psi-Arch, as
a foundational framework for self-constructing software... Although this paper
does not present a definitive solution, it seeks to catalyze discourse..."*

**What it actually does vs. the reviewer's claim.** The reviewer treats this as
"the closest *self-construction* prior art." It is narrower than that framing
implies: **it is an explicitly-labelled position paper** — "this paper does not
present a definitive solution." It proposes Ψ-Arch as a *direction*, not a
built or evaluated system. It is one self-rewriting program at the codebase
level — no concurrency, no peer artifacts, no in-flight unsettled state, no
task lifecycle, no multi-artifact integrity. The reviewer's residual
description (S1) is accurate; the reviewer's *weight* — "names the exact
scientific concept the plan's whole idea is" — overstates. Autopoiesis is a
biology term Ψ-Arch *borrows*; borrowing it in a position paper does not make
the plan's contribution a folk restatement of a built thing. **Verified, but
the reviewer over-states its standing: it is an aspirational position paper,
not a deployed or evaluated system.** It corroborates the direction; it does
not preempt the substrate.

### Paper B — arXiv:2605.12087, Intermediate Artifacts as First-Class Citizens

"Intermediate Artifacts as First-Class Citizens: A Data Model for Durable
Intermediate Artifacts in Agentic Systems" — Josh Rosen, Seth Rosen.

Verbatim (load-bearing extract): *"We argue that such systems should preserve
durable, inspectable intermediate artifacts: typed, structured, addressable,
versioned, dependency-aware, authoritative, and consumable by downstream
computation... The contribution is a systems-level data model... The claim is
not that artifacts make models smarter. It is that durable intermediate
artifacts make AI-generated work more inspectable, revisable, and maintainable
over time."*

**What it actually does vs. the reviewer's claim.** The reviewer's claim — it
"collides head-on" with the contribution sentence — is **accurate on the
vocabulary and correct that this is genuinely close**, but the paper itself is
explicit about its own narrowness in a way that protects the plan's residual.
Its abstract states the artifacts carry **no agency** ("inspect, revise,
supersede, and improve" — done *by* humans and agents *to* the artifacts) and
its "intermediate artifacts" are *completed* sub-products (evidence maps,
claim structures, plans) — not proposals-in-superposition mid-negotiation. So
the vocabulary collision is real and must be conceded: the plan can no longer
present "typed, dependency-aware, versioned, first-class intermediate
artifacts" *as a data model* as its own coinage. The residual — agency over
that data model, plus representing in-flight proposals as superposed rather
than as durable completed products — survives intact. **Verified, accurately
characterized as close, correctly narrowed by the reviewer.**

### Paper C — arXiv:2603.15690, Loosely-Structured Software

"Loosely-Structured Software: Engineering Context, Structure, and Evolution
Entropy in Runtime-Rewired Multi-Agent Systems" — Zhang, Zhou, Qu, Li.

Verbatim (load-bearing extract): the paper introduces a three-layer framework
including *"Evolution Engineering to govern the lifecycle of self-rewriting
artifacts"* and develops design patterns as *"semantic control blocks that
stabilize fluid, inference-mediated interactions."*

**What it actually does vs. the reviewer's claim.** The reviewer's claim —
"Endogenous Evolution: artifacts the system rewrites itself" — is **slightly
over-stated**. The fetched abstract frames LSS's artifacts as *files the
agents* programmatically rewrite ("runtime-rewired multi-agent systems";
agency described as agent autonomy plus artifact evolution). The artifacts are
the rewritten medium; they are not themselves negotiating peers carrying
wants. The reviewer's own residual (S3: "LSS's artifacts are passive files an
*agent* rewrites") is correct and contradicts the reviewer's headline phrasing
("artifacts the system rewrites itself"). **Verified; cite tersely; the
residual — agency *in* the artifact, not in the agents — is untouched.**

### Finding S1 — the autopoiesis naming question

**Decision: cite Ψ-Arch as a one-sentence prior-art neighbour. Do NOT adopt
"autopoiesis" as the plan's or the review's organizing vocabulary, and do NOT
add an autopoiesis subsection.**

Reasoning. Autopoisis (Maturana & Varela) is a *biology / systems-theory*
concept describing living cells that regenerate their own components. It is a
genuine intellectual ancestor of "self-maintenance" — worth one sentence of
lineage. But the reviewer's proposed edit (a §3 subsection, adopting the word
throughout, "the plan's 'self-maintenance' is a folk term for autopoiesis")
would *muddy* the contribution, not strengthen it. The plan's contribution is
a built data structure. Autopoiesis names an *aspiration* shared by a 50-year
biology literature and one 2026 position paper; renaming the plan's concrete
deliverable after a biology abstraction invites the exact "this is just
autopoiesis, already named" collapse the methodology warns against. The
methodology's rule applies: academic naming of an adjacent idea corroborates
the direction; it does not preempt building the substrate. One sentence of
lineage in the conclusion is the right dose. This is a **net cut** relative to
the reviewer's proposal (one sentence, not a subsection).

### Finding S6 — MAP-Elites against the §6 sliver

**Decision: reject the implied narrowing; the §6 sliver holds. Add nothing.**

The reviewer asks whether MAP-Elites' niche-local competition preempts part of
"negotiated internal selection." Verified against the QD literature: in
MAP-Elites the niches are **explicitly defined by the user**, and selection is
a new individual competing *against the single static elite occupant of its
bin* on a fixed fitness measure — there is no candidate-to-candidate
interaction, no negotiation, no candidate reasoning about its own survival.
"Local rather than global" competition in MAP-Elites is still external,
threshold-based selection. It does **not** preempt the sliver. §6's residual
("selection emerging from peer-to-peer negotiation among the candidates
themselves") stands as written. No edit; this avoids adding a MAP-Elites
paragraph the body does not need.

---

## Part 2 — Corrected-scope citation sentences (one each, terse)

These are the *only* sentences the three papers add to the body. Each goes
into Appendix B's compressed survey (or the conclusion's prior-art list), not
into expanded prose.

- **Ψ-Arch (2604.13934):** "A 2026 position paper, Ψ-Arch (arXiv:2604.13934),
  proposes 'autopoietic architectures' — software that self-constructs and
  self-maintains via a foundation-model reasoning unit — but as an
  aspirational single-program direction, not a built system, and with no
  concurrency, peer negotiation, or in-flight state; the plan applies the same
  self-maintenance aspiration to a population of negotiating artifacts."

- **First-Class Intermediate Artifacts (2605.12087):** "A 2026 data-model
  paper, 'Intermediate Artifacts as First-Class Citizens' (arXiv:2605.12087),
  proposes typed, versioned, dependency-aware durable intermediate artifacts —
  so the plan does not coin that data-model vocabulary; but its artifacts are
  passive completed work-products with no agency, where the plan's residual is
  agency over the structure plus representing in-flight proposals as
  superposed rather than as durable finished products."

- **Loosely-Structured Software (2603.15690):** "LSS (arXiv:2603.15690) names
  'Endogenous Evolution' — behavior-shaping files the multi-agent system
  rewrites — so 'artifacts that get rewritten' is not unprecedented; but LSS's
  artifacts are the medium agents rewrite, where the plan puts the agency in
  the artifact itself."

---

## Part 3 — Non-prior-art substantive findings (S4–S9)

- **S4 (convergence experiment under-specified) — ACCEPT, as a terse REWRITE,
  net ~0.** §5's convergence paragraph should name the protocol in one
  sentence: "run N artifact-pairs through forced-conflict negotiations;
  dependent measures: termination rate, oscillation rate, false-consensus
  rate, benchmarked against the timeout rule." This replaces existing hedging
  prose, not adds to it.

- **S5 (cost-stratification over-argued) — ACCEPT as a CUT.** This is the
  cycle's largest single trim opportunity. The §5 cost-stratification passage
  (~600 words: "the bet," "the hedge," "one caution on using this study for
  both sides") is cut to ~200 words: state the threshold finding, state the
  bet, state the one residual (benchmark-to-negotiation transfer), name the
  watcher fallback, stop. Delete the "caution on a caution" paragraph
  entirely. Net: **−400 words.**

- **S6 (MAP-Elites/§6) — REJECT (see Part 1).** No edit.

- **S7 (MMP CAT7 fixed-schema fitness) — ACCEPT, as a one-sentence ADD folded
  into an existing cut.** §2 already says CAT7 is "one point in that design
  space." Add half a sentence: a fixed-field schema fits *typed knowledge*
  but is likely wrong for *unsettled work state*, which argues for a more open
  representation. This rides inside the §2 trim (Edit 9) — net negative for
  the section overall.

- **S8 (no empirical contradiction for "human as boundary") — ACCEPT, terse
  ADD ~45 words, paired with a conclusion CUT.** Add one sentence to the §5
  convergence area: the boundary claim is in tension with measured 41–86.7%
  multi-agent failure rates, so the honest framing is "human-at-boundary is
  the goal state reached as integrity-maintenance matures, not a day-one
  property." Pay for it by cutting the conclusion's redundant restatement of
  the same boundary point (Edit 12).

- **S9 (§7 experiment lacks a dependent measure) — ACCEPT, terse REWRITE,
  net ~0.** §7's verdict sentence gains a DV: "...rated by a blind judge for
  number and quality of self-maintenance tasks generated, on a fixed set of
  artifacts with known coherence defects." Replaces, not adds.

---

## Part 4 — Structural cut (the load-bearing edit)

Move the §§1–7 prior-work survey **detail** into a new **Appendix B —
Prior-Art Survey**, mirroring how Appendix A already holds the Claude Code
walk. The body keeps only what a non-developer needs to reach the verdict.

**Stays in the body (lean, navigable by a non-developer):**
- Executive summary (tightened — Edit 13).
- Introduction (the plan's claims, the four glossed terms).
- §9 (the four concrete pm instances) — promoted to directly after the
  introduction, per ST5.
- The conclusion (the four-step contribution case, the MMP comparison, "Read
  on the framing," "Coverage gaps").
- A new ~250-word **"§ Prior art in brief"** stub replacing §§1–8: one
  paragraph per cluster (classical coordination; CRDT/OT; living-document
  vision; LLM agents/LLM-OS; self-organizing agents; evolutionary computation;
  anthropomorphization; Claude Code) — each two-to-three sentences, each
  ending "full treatment in Appendix B."

**Moves to Appendix B (the dense survey):** the per-system walks of §§1–7 —
actor model, contract-net, blackboard, Linda, OT, CRDTs, Engelbart, Victor,
Knuth, Minsky, MemGPT, Karpathy, MAIF, AutoGen/MetaGPT/ChatDev, stigmergy,
market coordination, Semantic Consensus, SwarmSys, AgentNet, ScienceClaw,
AgentsNet, Drop-the-Hierarchy, Agora-Opt, the §6 evolutionary-computation
walk, §7 persona detail. §8 (Claude Code) already has its detail in Appendix
A — collapse §8's body text to three sentences pointing at Appendix A.

This is a relocation, not a deletion: total document word count drops because
the body's connective prose, re-glossing, and cross-references collapse, and
because §§2 and 5's over-argued passages are trimmed *as they move*.

---

## Part 5 — Numbered edits checklist (apply in order)

Running net-words estimate in brackets after each edit. Negative = good.

1. **REWRITE/RESTRUCTURE.** Create `## Appendix B — Prior-Art Survey` after
   Appendix A. Move the full text of current §§1–7 into it under their
   existing headings. In Appendix B, *as you move them*: apply the §2 trim
   (S7 + remove duplicated CRDT-for-LLM hedging) and the §5 cost-stratification
   trim (S5). Net for the move itself ~0; the trims net **−500**. [−500]

2. **ADD.** In Appendix B §3, append the Ψ-Arch sentence (Part 2). [−480]

3. **ADD.** In Appendix B §4 (after MAIF), append the LSS sentence and the
   First-Class Intermediate Artifacts sentence (Part 2). [−445]

4. **REWRITE.** Appendix B §5, convergence paragraph: replace the
   "timeout-into-dropped rule is the right kind of safeguard" hedge with the
   S4 named protocol sentence. Net ~0. [−445]

5. **ADD.** Appendix B §5, near the convergence paragraph: the S8 sentence on
   41–86.7% failure rates and "human-at-boundary as goal state." +45. [−400]

6. **REWRITE.** Appendix B §7, verdict: add the S9 dependent measure to the
   experiment sentence. Net ~0. [−400]

7. **CUT.** Delete §8's body prose; replace with three sentences: Claude Code
   assumes a static-config + reactive-session split with no between-sessions
   first-class artifact; the frontier (InfiAgent, "Everything is Context")
   builds file-as-state but passive/human-curated; the plan's residual is
   agency in the externalized artifact. Move the deleted detail's evidentiary
   weight to Appendix A (already present). Net **−550**. [−950]

8. **ADD.** Insert new body section `## Prior art in brief` (~250 words, eight
   short cluster paragraphs, each pointing at Appendix B) where §1 used to
   begin. +250. [−700]

9. **REWRITE.** Renumber: the body is now Executive summary → Introduction →
   "The plan's instances, grounded in pm" (the old §9, promoted per ST5) →
   "Prior art in brief" → Conclusion → Appendix A → Appendix B. Update all
   cross-references ("Section 5", "§9", "see Section 6" etc.) to point at
   Appendix B subsections or the renumbered body. Mechanical; net ~0. [−700]

10. **CUT.** Conclusion, "The other close prior art points the same way"
    paragraph: compress to two sentences per ST3 ("Every close prior-art work
    surveyed corroborates the plan's direction on a narrower slice; none builds
    the general self-maintaining artifact substrate — that layer is the plan's
    job."). Net **−180**. [−880]

11. **CUT.** Conclusion / "Read on the framing": the "relocated, not
    eliminated" / "narrowed but intact" argument is fully stated once (keep it
    in the §5 relocation passage now in Appendix B; in the conclusion refer
    back in one clause). Remove the ~3 redundant restatements per P1. Net
    **−160**. [−1,040]

12. **CUT.** Conclusion §(d): remove the redundant standalone restatement of
    the "human as boundary" point now that S8's sharper version lives in
    Appendix B §5 (Edit 5). Net **−70**. [−1,110]

13. **REWRITE.** Executive summary, per A1: replace "the contribution
    narrowed" with "though the plan should claim less as brand-new than it
    might want to"; replace "prunes a tangle of conflicting research outputs"
    with "automatically cleans up when automated research tools produce
    contradictory or duplicated results"; gloss "substrate" once as "the
    common underlying machinery everything is built on," then use "foundation"
    elsewhere in the summary. Net ~0. [−1,110]

14. **REWRITE.** Body first use of "substrate": add the five-word gloss per
    A2. Then leave the term as-is (it is defined). Net +12. [−1,098]

15. **CUT.** Prose tics across the now-shorter body and conclusion: remove
    excess "genuine/genuinely" (P6), "stated precisely/plainly" pivots (P4),
    and roughly half the em-dashes (P2). Estimated **−120** across the
    surviving body text. [−1,218]

16. **REWRITE.** Introduction paragraph that previews "eight sections" — the
    body no longer has eight sections. Update to describe the new structure
    (instances, prior-art-in-brief, conclusion, two appendices) in two
    sentences. Net **−40**. [−1,258]

**Projected net word change: approximately −1,260 words.**
Document: ~15,970 → **~14,710 words** in the body+appendix total *as counted*.

Note on the target: Edits 1–16 net −1,260 with confidence. The reviewer's
~12,000 aspiration would require deeper compression of Appendix B's prose
itself (the per-system walks). The apply agent SHOULD, while moving §§1–7 into
Appendix B, additionally tighten each per-system walk by ~25% (cut deadwood,
collapse double-glosses, drop the P3/P5 hedge-stacks) — that is a further
~−2,000 to −2,500 words and brings the total to ~12,200–12,700. This deeper
trim is in-scope and encouraged; it is not separately enumerated above only
because it is line-level copy-editing rather than discrete edits. **The
mandatory floor is net −1,260; the goal is net −3,500.**

**Hard rule for the apply agent:** if the finished pass nets positive, it has
failed this cycle's load-bearing constraint and must be redone before commit.
The body proper (everything before Appendix A) must be readable end-to-end by
a non-developer in well under 4,000 words.

---

## Summary of decisions

- Three papers ADDED, one terse sentence each, all into Appendix B.
- Autopoiesis: one sentence of lineage only; NO subsection, NO vocabulary
  adoption — rejected as contribution-muddying.
- S4, S5 (cut), S7, S8, S9 accepted as terse rewrites/cuts; S6 rejected.
- Structural: §§1–7 detail → Appendix B; body reduced to exec summary,
  intro, pm instances, prior-art-in-brief, conclusion.
- 16 edits; projected net **−1,260 words minimum**, goal **−3,500**.
