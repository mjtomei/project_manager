# Review Cycle 2 — Literature Review: Living Artifacts

**Artifact:** `pm/docs/literature-review-living-artifacts.md` (~13,298 words)
**Reviewer:** Fresh adversarial pass, blind to prior cycles at drafting time.
**Date:** 2026-05-15
**Methodology:** `pm/docs/adversarial-review/METHODOLOGY.md` — four blocks, step-5 citation-graph walk, narrow-don't-collapse.

Prior-cycle files (`REVIEW_CYCLE_1_LIVING_ARTIFACTS.md`, the response files) were not read before this review was drafted. A "what prior cycles missed" appendix at the end was added after the independent review, by scanning them.

---

## Summary verdict

The review is in good shape. It is honest about lineage, it does the narrowing work, and the MMP and MAIF comparisons are mostly fair. But this is a Cycle 2 pass and the methodology demands more findings than Cycle 1, with prior fixes already incorporated — so the bar is "what is still wrong," not "is it broadly OK." It is broadly OK; it also has one substantive prior-art miss, one substantive over-claim the prior cycle's "keep the framing" decision shaded past, and a cluster of accessibility failures the load-bearing Block 3 has not been held to.

**Findings: 23 total — 6 substantive, 17 phrasing/accessibility/structure.**

The single most important finding is **SUBSTANTIVE-1**: a 2025-2026 line of work explicitly reviving the *blackboard architecture* for LLM multi-agent systems — and explicitly deleting the central controller — exists, is directly on the review's core thesis, and is not cited. The review treats "blackboard" as forty-year-old prior art and as a vocabulary word; it is in fact a *live, competitive 2026 research program* doing a recognizable version of "blackboard without a scheduler." That is exactly the plan's Instance 1 framing, and it has been published.

---

## Block 1 — Substance

### SUBSTANTIVE-1 — The blackboard revival is missing, and it is the closest structural prior art to Instance 1

The review's §1 treats blackboard systems as 1980s history (Hearsay-II, Nii 1986) and uses "blackboard" as a vocabulary word for Instance 1 ("the plan is a blackboard without a scheduler"). The conclusion §(a) lists blackboard systems among the "old visions." Nowhere does the review acknowledge that **the blackboard architecture is the subject of an active 2025-2026 LLM-multi-agent research program**, and that program is doing the *specific move the review credits the plan with*.

The citation-graph walk surfaced two papers:

- **"Exploring Advanced LLM Multi-Agent Systems Based on Blackboard Architecture" (arXiv:2507.01701, 2025).** Verbatim from its framing: "the ancient blackboard AI architecture can revive and facilitate the development of agentic systems with the power of LLMs." It posts a request on a shared blackboard; subordinate agents monitoring the blackboard "independently decide whether they possess the capability, knowledge, or interest to contribute" — i.e., **the control component is gone and self-selection replaces it.**
- **"LLM-Based Multi-Agent Blackboard System for Information Discovery in Data Science" (arXiv:2510.01285, 2025; OpenReview egTQgf89Lm).** It reports the blackboard architecture "substantially outperforms baselines, achieving between 13% to 57% relative improvement," and explicitly "shifts decision-making from a single coordinator to a distributed model whose agents autonomously determine their participation."

**Why this matters — narrow, don't collapse.** The review's §1 claim "*the plan is a blackboard without a scheduler*" is presented as the plan's *novel synthesis* — the plan inherits the shared workspace and "deletes the control component." But arXiv:2507.01701 and arXiv:2510.01285 already deleted the control component, on a blackboard, with LLM agents, and shipped the result with measured gains. The plan is therefore **not the first to build an LLM-driven blackboard with no central controller.**

What the prior art does (from the abstracts/framings above):
- Shared workspace LLM agents read and write.
- Agents self-select participation; no central scheduler.
- Empirically evaluated (13-57% gain on information-discovery tasks).

What the plan does that this prior art does not:
- The blackboard itself has *agency* — it spawns self-maintenance tasks from "wants." In arXiv:2507.01701/2510.01285 the blackboard is still passive shared state; the agents act, the board does not.
- The board carries *in-flight, unsettled task state as first-class* — proposals in superposition, negotiation history. The LLM-blackboard papers post findings; they do not model competing in-flight proposals negotiating their own convergence.
- The unit is the durable project artifact (plan, PR, pm itself), not an ephemeral task board.

**Proposed replacement contribution statement (for §1 and conclusion §(a)):**
Replace "*the plan is a blackboard without a scheduler*" — which now reads as preempted — with: "*The blackboard-without-a-controller pattern is itself being rebuilt for LLM agents right now (arXiv:2507.01701, arXiv:2510.01285); the plan inherits that pattern. What the plan adds is a blackboard that is itself an agent — it carries its own wants and spawns its own maintenance tasks — and that holds competing in-flight proposals as first-class state, not just posted findings.*"

This is a genuine miss. The review's seed list should have walked "blackboard" forward; it walked the LLM-agent seeds forward but treated the four classical systems as static. METHODOLOGY step 5b says walk *both directions on every seed* — the classical seeds were only walked backward.

### SUBSTANTIVE-2 — "From Soliloquy to Agora" preempts a slice of the conflict-resolution claim

The walk surfaced **"From Soliloquy to Agora: Memory-Enhanced LLM Agents with Decentralized Debate for Optimization Modeling" (arXiv:2604.25847, 2026).** From its abstract: agent teams "independently produce end-to-end solutions and reconcile them through an outcome-grounded debate protocol," and "decentralized debate offers a structural advantage over centralized selection by enabling agents to refine candidate solutions through interaction and even recover correct formulations when all initial candidates are flawed."

This is *intelligence-resolved conflict resolution between concurrent candidate artifacts, decentralized, no central selector* — a recognizable instance of the review's core thesis ("resolves conflicts via intelligence," "no central adjudicator"). It is not the plan (it is scoped to optimization-modeling problem formulations, has no self-maintaining artifact, no wants, no task lifecycle) — but the review's conclusion §(c) presents "intelligent conflict resolution as a primitive" as "genuinely new," and §(b)'s "there was no third option" framing implies nobody has put judgment-based reconciliation in place of a deterministic rule or central arbiter. Agora-Opt did, for its slice. The review should cite it in §5 (self-organizing coordination) and soften §(c) from "genuinely new" to "now being built by independent groups on narrower problems — Agora-Opt does outcome-grounded decentralized reconciliation; the plan generalizes the pattern to a self-maintaining artifact substrate." This is a narrowing, not a collapse: the plan's residual (general artifact, wants, lifecycle) survives.

### SUBSTANTIVE-3 — The InfiAgent / "Everything is Context" file-centric-state line is the closest prior art to Instance 3, and is absent

§9 Instance 3 ("pm becomes a renderer and host; `project.yaml` no longer holds workflow state") and the conclusion's "first-class, between-sessions artifact" claim have a direct, very recent neighbor the review never names:

- **InfiAgent (arXiv:2601.03204, Jan 2026)** "externalizes long-term state into a file-centric representation, treating the file system as the authoritative and persistent record of the agent's actions, environment, and intermediate artifacts." That is structurally the plan's "the artifact, not a state machine, holds the workflow state."
- **"Everything is Context: Agentic File System Abstraction for Context Engineering" (arXiv:2512.05470, Dec 2025)** is the same move.

The review's §8 confronts Claude Code's "static-config + reactive-session split" and claims "there is no abstraction in Claude Code for an artifact that is continuously co-authored and lives between sessions as first-class state." That is true *of Claude Code*, but the review then implies the *idea* of a between-sessions first-class artifact is the plan's contribution ("the living-artifacts data structure is the missing middle"). InfiAgent and "Everything is Context" are exactly "make the persistent artifact, not the session, the authoritative state." The plan's residual over these is real (the artifact has agency/wants; it negotiates; it is not just a passive externalized-state store) — but the review must cite them and narrow the §8/conclusion claim from "the missing abstraction" to "Claude Code lacks this abstraction; the research frontier (InfiAgent, 'Everything is Context') has converged on file/artifact-as-authoritative-state; the plan's addition is agency in that artifact, not the externalization itself."

### SUBSTANTIVE-4 — The "keep the framing" decision shades into overclaim at the conclusion's §(c)

The plan's framing was kept rather than narrowed (a deliberate prior-cycle decision). Mostly that holds — the review does narrow the four sub-claims. But §(c) "What LLMs change — intelligent conflict resolution as a primitive" still contains an unhedged absolute: "**This is the enabler, and it is genuinely new.**" And: "The third option that did not exist for Engelbart, for the blackboard designers, for Gelernter — *put the judgment in the unit* — exists now."

Given SUBSTANTIVE-1 and SUBSTANTIVE-2, "genuinely new" is too strong as a 2026 statement. Putting LLM judgment in the resolution step is what CodeCRDT's own follow-on motivation, the LLM-blackboard papers, Agora-Opt, and Semantic Consensus *all do*. What is new is not "intelligent conflict resolution as a primitive" — that primitive is now widespread — but *making it the resolution mechanism inside a self-maintaining general artifact*. The honest §(c) sentence: "What LLMs change is that intelligent conflict resolution becomes cheap enough to instantiate *inside a data structure*; multiple 2025-2026 systems now do this for narrow slices, and the plan's move is to make it the resolution layer of a general, self-maintaining artifact substrate." Keep the framing's *direction*; cut the word "genuinely new."

### SUBSTANTIVE-5 — The time-relativity / cost-stratification "bet with hedge" is honest about safety but still soft on one number

§5's rewrite (the "bet" / "hedge" treatment) is good — it is a real improvement and it does engage the economics. It explicitly names the interim throughput cost ("watchers may spend their time redoing a steady stream of cheap-tier proposals"). That is the honest move and it should stay.

But one quantitative anchor is missing and it is the load-bearing one. The bet is "the capability-per-dollar curve keeps moving." "Drop the Hierarchy" actually supplies a *number the review does not use*: open-source models reached **95% of closed-source quality at 24x lower cost**. That is direct evidence *for* the bet — the cheap tier is already within 5% of the frontier on that study's tasks — and the review omits it while citing the same paper's threshold finding *against* the bet. Citing only the bearish half of a paper you lean on is a selective read. The review should add: "'Drop the Hierarchy' also found open-source models at 95% of closed-source quality for 24x less cost — direct evidence the routine tier is already near-capable; the open risk is whether 'near-capable on benchmark tasks' transfers to 'capable enough to negotiate without degrading integrity,' which the study does not test." That makes the bet's evidence two-sided and the residual uncertainty precise.

### SUBSTANTIVE-6 — No empirical-contradiction stress on the headline mechanism

METHODOLOGY Block 1 asks: "what empirical data contradicts the key points?" The review handles this *for cost-stratification* (the threshold finding) and *for syntactic-vs-semantic merge* (CodeCRDT's 5-10%). But the headline claim — "no central adjudicator; conflicts resolve through peer negotiation against an integrity constraint" — has a contradiction in the review's own evidence base that is never confronted as a contradiction.

"Drop the Hierarchy" found the **hybrid beat fully-autonomous coordination by 44%**. The review treats this (§5) as "narrow the wording to 'no central adjudicator.'" Fine — but it never asks the harder question: the plan's integrity-pressure mechanism *is the adjudication*, just relocated into the artifact and the maintenance tasks. If "fully autonomous underperforms," and the plan's integrity-maintenance task is the thing that catches a bad proposal, then the integrity-maintenance task is functionally a soft adjudicator with extra steps. The review should state plainly: "the plan's 'no central adjudicator' is precise about *form* (no manager-intelligence above the artifact) but the integrity-maintenance task plays an adjudication-like *role*; whether distributing that role across maintenance tasks beats concentrating it is exactly the open empirical question, and 'Drop the Hierarchy' tilts mildly toward concentration." Right now §5 narrows the wording but does not surface that the plan may have re-invented adjudication under a different name. That is the sharpest unaddressed contradiction.

---

## Block 2 — Structure

### STRUCT-1 — The review is too long and front-loads its own conclusion

13,298 words is long for "a reader evaluating whether the plan's bet is supported." The Introduction's "What surrounds the plan" already states the whole verdict ("almost every primitive the plan needs already exists"; the MMP/MAIF callout). The conclusion then restates it across seven subsections. A reader who reads the intro and the conclusion has read the review twice. **Cut the conclusion's §(a) and §(b) by half** — they re-narrate §§1-3, which the body already did. The conclusion should be MMP + the framing read + coverage gaps; the "old vision / determinism constraint" material is already in §1 and the intro.

### STRUCT-2 — §8 (Claude Code grounding) is the longest section and the least load-bearing for the stated audience

§8 is a feature-by-feature CLAUDE.md/hooks/skills/plugins/subagents/MCP/agentic-search/plan-mode walk. For "a non-developer evaluating whether the plan's bet is supported by prior work," this is an internal product-comparison, not prior-art. It is valuable but it is in the wrong document — it is competitive analysis, not literature. Recommend compressing §8 to ~3 paragraphs (the static-config/reactive-session gap; the agent-manager contrast; the scoping note) and moving the feature-by-feature table to an appendix or the plan itself. As written it is ~1,400 words and breaks the review's spine.

### STRUCT-3 — §9 duplicates §8 and the conclusion

§9 ("the plan's instances") re-walks Instances 1-4, each with "pm today / living-artifact version / what it enables / prior-work cluster." The "prior-work cluster it draws on" lines just point back to §§1-5. The conclusion §(d) then walks the same four instances again. Three passes over the same four instances. Keep §9 (it is the most concrete part); cut the instance re-walk from conclusion §(d) to one sentence.

### STRUCT-4 — Section 7's verdict paragraph repeats itself

§7 makes its three points, then the "Verdict for the plan" paragraph re-states all three. The verdict paragraph is ~190 words restating ~190 words. Cut the verdict to: "Persona prompting is an established lever; the artifact-as-wanting variant is untested; run the cheap controlled comparison." Three clauses.

---

## Block 3 — Non-expert accessibility (load-bearing)

The target reader is a non-developer evaluating whether the plan's bet is supported. The review *does* gloss heavily — the Introduction's term list is good, and most CS primitives get an inline plain-language analogy (the "office with locked drawers" for actors, "subcontracting" for contract-net). That is real effort and it mostly works. But the load-bearing block must be held to a hard standard, and there are misses.

### ACCESS-1 — "CRDT" and "operational transformation" are glossed; "strong eventual consistency," "causality preservation," "convergence" are used load-bearingly and under-glossed

§2 defines CRDT and OT well. But then: "Its two guarantees — that edits are applied in an order respecting which edit came first (*causality preservation*), and that every copy ends up identical (*convergence*)." The parenthetical *names* the term but the term then recurs ("deterministic convergence," "perfect CRDT convergence," "guaranteed syntactic convergence") assuming the reader retained it. A non-developer will not. **Fix:** after first use, stop using the term "convergence" and say "all copies end up identical" each time, or accept one gloss and never use the bare word again. Right now the review uses "convergence" 6 times, glossed once.

### ACCESS-2 — "semantic" vs "syntactic" is the single most load-bearing distinction in the review and is never cleanly glossed for a non-developer

The whole thesis rests on "a CRDT guarantees the *text* merges; it does not guarantee the *meaning* is coherent" (§2, §conclusion). The review uses "semantic conflict," "semantic layer," "syntactic convergence," "semantic intent divergence" throughout. A non-developer does not reliably know "syntactic = form/text, semantic = meaning." The §2 line "semantic (meaning-level, not syntactic)" glosses it *once, in a parenthetical, mid-sentence.* For the load-bearing distinction of the entire review, that is not enough. **Fix:** add a standalone sentence early in §2: "Two words recur below. *Syntactic* means the literal text — the characters on the page. *Semantic* means what the text means. A merge can succeed syntactically (the characters combine without a clash) and still fail semantically (the combined result no longer makes sense). That gap is what this review is about." Then the term is earned.

### ACCESS-3 — "stigmergy" is glossed; "superposition" is not

§5 glosses stigmergy well (ants, pheromone trails). But the plan's phrase "proposals exist in superposition" is quoted in the review (intro point and §5's "Drop the Hierarchy" discussion) with no gloss. "Superposition" is a physics borrowing meaning "many possible states held at once, not yet collapsed to one." A non-developer reads it as jargon-for-effect. **Fix:** on first quote, append "— that is, many possible versions of the document are held at once, none of them yet the final one." Or recommend the plan drop the word; the review at minimum must gloss it where it quotes it.

### ACCESS-4 — Acronyms introduced and then leaned on without re-anchoring

- **OT** — spelled out once (§2), then used as "OT" repeatedly. For this audience, "operational transformation (OT)" then bare "OT" four sections later is a lookup. Either re-spell or say "the transform-on-the-fly technique."
- **EA** — §6 introduces "evolutionary algorithm (EA)" then uses "EA" / "the plan's EA direction." Same issue.
- **CMB** — §conclusion ("MMP's unit, the Cognitive Memory Block") then "a CMB" / "what a CMB is." A reader four paragraphs later has lost it.
- **SVAF, CAT7** — §conclusion's MMP comparison uses "CAT7," "SVAF" repeatedly. CAT7 gets a gloss ("a fixed seven-field typed schema"); SVAF gets "per-field, role-indexed acceptance — a receiver decides field by field what to take from a peer," which is itself dense. For the target reader, "SVAF" should just be "MMP's accept-field-by-field rule" every time, no acronym.

**Fix:** the review invented a rule for itself in the intro (gloss on first use). It does not hold the rule across 13,000 words. Either re-gloss at section boundaries or replace acronyms with plain phrases after first use.

### ACCESS-5 — Names dropped without the "why we mention it"

METHODOLOGY Block 3 requires every named work to carry "what it is and why we mention it." Mostly the review does this. Misses:

- **"Yjs"** (§2) — "a Yjs (a popular CRDT library) collaborative document." The parenthetical says what Yjs is but the target reader does not know what a "CRDT library" is even after the §2 gloss of CRDT-the-concept (a *library* is a reusable code package). **Fix:** "a ready-made software component (Yjs) that implements CRDTs."
- **"SQLite"** (§1, §plan-open-questions) — glossed once in §1 ("a lightweight single-file database"), used again later unglossed. Fine-ish, but the §1 gloss is in a parenthetical inside a long sentence about Carvalho's essay; a reader may miss it.
- **"Strassen's 1969 matrix-multiplication algorithm"** (§6, AlphaEvolve) — dropped with zero gloss. The target reader has no idea what this is or why "improved on it" is impressive. **Fix:** "improved on a 1969 result for multiplying matrices that had stood for decades — a striking sign the method finds real mathematics."
- **"the cap-set problem"** (§6, FunSearch) — same. Cut it or gloss it ("an open problem in pure mathematics").

### ACCESS-6 — "Why should I care?" — three section openings fail the check

- **§2 opens:** "The plan's open questions ask, directly: 'What is the artifact's persistent representation? ... CRDT-friendly...'" — opens on a quoted technical question. The target reader does not yet know why they should read a section about data structures. **Proposed opening:** "Can many edits happen to one document at the same time without a referee deciding the order? This section shows that problem was solved decades ago — so it is not a risk the plan carries."
- **§4 opens:** "This is where the plan's prior art is most recent and most directly competitive." — better, but "prior art" is itself jargon for this audience (it means "earlier work that might already cover the idea"). **Fix:** "This section covers the work that comes closest to the plan — recent enough that it could undercut the plan's claim to be new. It is also where the plan's biggest claim, 'no central manager,' gets tested."
- **§6 opens:** "The plan's 'Where this leads' section claims..." — opens by quoting the plan. **Fix:** "The plan makes one ambitious side-claim: that living artifacts could change how evolutionary algorithms work. This section checks whether that claim is new — and finds most of it is not."

### ACCESS-7 — "actor model," "tuple space" — glossed well; "operational transformation" example is the one a non-developer will not follow

§2's OT gloss: "if you insert a word at position 5 while I delete a word at position 2, my client adjusts your insert to position 4 before applying it." This is the *correct* explanation but it assumes the reader tracks character-position arithmetic in their head. **Fix:** lead with the outcome, not the mechanism: "if two people edit the same sentence at once, the system quietly rewrites each person's edit so that, applied together, they don't clobber each other and both people end up seeing the same final sentence." Keep the position-5 example as a follow-on for readers who want it, explicitly marked optional.

### ACCESS-8 — "non-deterministic" — the review flags the plan's misuse but then uses the term itself

§conclusion §(d) correctly says the plan's word "non-deterministic" is "imprecise." Good catch. But the review's *own* Introduction, the very first sentence of the document's subtitle context, and the framing throughout lean on "unsettled state as first-class," which is the right phrase — except the review never defines "first-class" for a non-developer. "First-class" is programming jargon ("treated as a full citizen of the system, not a second-class add-on"). It appears ~8 times. **Fix:** first use: "unsettled state as first-class — meaning the half-finished, still-being-argued-over version of the document is stored and handled as seriously as the finished version, not bolted on as an afterthought."

---

## Block 4 — Prose

### PROSE-1 — Emphasis density

The review italicizes constantly. Sample from §1: "*Mostly, yes.*" "*right*" "*reason*" "*who runs a fixed task*" "*content of the proposal itself*" — five italic spans in one paragraph. Used this densely, italics stop emphasizing. **Fix:** allow one italic per paragraph. The argument carries itself; the italics are a verbal tic. Same problem with bold: §intro's plan-claims list bolds the lead of every bullet, which is fine, but the body then bolds mid-sentence ("**supporting evidence rather than a competing claim**," "**deletes the control component**") — pick structural bold (headers, list leads) and drop rhetorical bold.

### PROSE-2 — "the plan should" — repetitive imperative

The review tells the plan what to do dozens of times: "the plan should adopt this word," "the plan should cite," "the plan should narrow," "the plan should say so plainly," "the plan should claim the lineage proudly." It is a lit review, not an edit list — and the repetition flattens. Count in §1 alone: "should" appears 9 times. **Fix:** consolidate per-section recommendations into one "what the plan should change" sentence at each section's end, and let the body just *report* the prior art.

### PROSE-3 — Long sentences with buried main clauses

§5, the CodeCRDT bullet: "That 5-10% residual is exactly the gap the plan's 'intelligence resolves conflicts' thesis is built to fill: a separate research group, working independently on a narrower slice, has now measured the precise size of the hole that the plan's intelligence-resolved layer is designed to close." Two independent clauses, a colon, three subordinate phrases. **Rewrite:** "That 5-10% residual is the gap the plan's intelligence-resolved layer is built to fill. An independent group has now measured that gap precisely — which makes CodeCRDT supporting evidence for the plan, not a competitor."

### PROSE-4 — Hedging tics

"*partly* true and *partly* not" (§1), "*Mostly, yes.*" (§1), "appears to humans with a cursor" (§2), "feel right when surfaced" (quoting plan, fine). Most are fine because they hedge real uncertainty. But §1's "The plan's diagnosis of these four systems holds up; one of its two clauses does not" — "holds up" then "one ... does not" in the same breath is self-contradicting on first read. **Rewrite:** "The plan's diagnosis is half right. One of its two clauses is true of all four systems; the other is true of only one."

### PROSE-5 — "worth stating" / "worth being precise about" / "worth drawing" — filler

The review repeatedly announces that something is worth doing instead of doing it: "Worth stating, so the inheritance is not overclaimed" (§3), "*A note on a naming collision worth being precise about*" (§5), "the comparison is worth drawing in detail" (§conclusion). **Fix:** cut the announcement, keep the content. "A note on a naming collision worth being precise about" → "The academic SwarmSys and the commercial Swarms are different things."

### PROSE-6 — The conclusion's MMP paragraph is restated verbatim as a block quote

§conclusion's "Stated as the plan's contribution:" paragraph (the italic block) re-states the three preceding paragraphs almost sentence-for-sentence. It is ~280 words of restatement. Either the three analytic paragraphs or the italic summary should go — not both. Keep the italic block (it is the cleaner version) and cut the three paragraphs above it to a two-sentence lead-in.

---

## Step 5 — Citation-graph walk

### Seeds (listed before searching, per METHODOLOGY 5a)

1. Mesh Memory Protocol (arXiv:2604.19540) — most load-bearing recent seed.
2. MAIF (arXiv:2511.15097).
3. CodeCRDT (arXiv:2510.18893).
4. "Drop the Hierarchy and Roles" (arXiv:2603.28990).
5. SwarmSys (arXiv:2510.10047).
6. Semantic Consensus (arXiv:2604.16339).
7. Blackboard systems (Hearsay-II / Nii 1986) — classical seed, walked forward.
8. CRDTs (Shapiro 2011) / contract-net (Smith 1980) — classical seeds, walked forward for LLM-era descendants.

### Coverage

Date range targeted: last 12 months, with emphasis on Dec 2025 – May 2026. Searched Google Scholar surface, arXiv, OpenReview, ResearchGate, alphaXiv, lab pages. Per-seed walk, ~5-8 min each.

| Seed | Direction | New work found | On-thesis? |
|---|---|---|---|
| MMP 2604.19540 | verified abstract; forward | A-Mem, MIRIX, Intrinsic Memory Agents — all *agent memory*, not work-coordination; not on-thesis | no |
| MAIF 2511.15097 | verified abstract | nothing closer than already cited | — |
| CodeCRDT 2510.18893 | verified; forward | Knowledge-Guided Multi-Agent code-gen, IaC orchestration — orchestrator-centric, not new | no |
| Drop the Hierarchy 2603.28990 | verified; forward | **Hyperagents (2603.19461)** — self-referential self-improving agents; relevant to §6 EA direction | partial |
| SwarmSys 2510.10047 | forward | nothing closer | — |
| Semantic Consensus 2604.16339 | forward | "Scaling Multi-agent Systems: Smart Middleware" (2604.03430) — middleware, same family as Semantic Consensus | minor |
| Blackboard (classical) | **forward** | **arXiv:2507.01701, arXiv:2510.01285 — LLM-blackboard revival** | **YES — see SUBSTANTIVE-1** |
| CRDT / contract-net | forward | **InfiAgent (2601.03204), "Everything is Context" (2512.05470)** — file/artifact-as-authoritative-state | **YES — see SUBSTANTIVE-3** |
| (topic walk) | "decentralized debate" | **"From Soliloquy to Agora" (2604.25847)** | **YES — see SUBSTANTIVE-2** |
| (topic walk) | "multi-agent shared memory consistency" | **"Multi-Agent Memory from a Computer Architecture Perspective" (2603.10062)** | partial — see below |

### Walk findings — new prior art the review should add

1. **arXiv:2507.01701 + arXiv:2510.01285 (LLM-blackboard revival)** — SUBSTANTIVE-1. The biggest miss.
2. **"From Soliloquy to Agora" (arXiv:2604.25847)** — SUBSTANTIVE-2.
3. **InfiAgent (arXiv:2601.03204) + "Everything is Context" (arXiv:2512.05470)** — SUBSTANTIVE-3.
4. **Hyperagents (arXiv:2603.19461, Meta)** — self-referential self-improving agents (task agent + meta agent merged into one editable program). Relevant to §6: it is a 2026 self-improving-system data point that sits alongside ADAS. The review's §6 says "in every system above, an external loop still drives selection." Hyperagents *merges* the meta-loop into the agent — closer to "internal" than ADAS, though still not negotiated peer selection. The review should cite it and note the §6 residual ("negotiated internal selection") narrows slightly further: Hyperagents internalizes the *improvement* loop but not *negotiated* selection. Residual survives, narrowed.
5. **"Multi-Agent Memory from a Computer Architecture Perspective" (arXiv:2603.10062)** — a position paper naming "multi-agent memory consistency" (concurrent read/write to shared agent memory) as the central open challenge, framed via classical memory-consistency protocols. This is relevant to the plan's open question "CRDT-friendly for concurrent in-flight task state." The review's §2 says "the plan's concurrency substrate is not a research risk." arXiv:2603.10062 says the *multi-agent* version of that substrate is explicitly an *open* problem. Mild tension: §2's "not a research risk" is true for two-human-CRDT editing but the review should note that multi-*agent* concurrent shared state is named as unsettled by a 2026 position paper, so the plan's substrate choice is on slightly less settled ground than §2 implies.

### Convergence signal

The walk found three on-thesis misses (blackboard revival, Agora, InfiAgent line). That is *more* prior art than a Cycle-2 walk should ideally surface if Cycle 1 was thorough — it suggests Cycle 1's walk under-covered the classical-seed forward direction and the "decentralized debate / file-centric state" topic clusters. Not a convergence signal yet; Cycle 3's walk should re-check whether anything published in May 2026 lands even closer.

---

## Pressure-test of the four prior-cycle rewrites

### The MMP comparison — fair and accurate, mostly

Verified against arXiv:2604.19540. MMP's stated subject (search result, verbatim framing): "cross-session agent-to-agent cognitive collaboration," with three challenges — field-by-field acceptance (P1), claim-to-source traceability so echoes are recognized (P2), and storage-time relevance for restart-surviving memory (P3). The review's characterization — "MMP coordinates knowledge between agents; it has no task concept, no scheduling, no self-organization of work" — is **accurate.** MMP genuinely has no task/scheduling concept; "mesh" genuinely is a sharing topology.

The contribution-narrowing statement ("the plan is not the first typed, semantically-merged, cross-session shared memory — MMP runs that") is **honest and correctly bounded** — it neither over- nor under-states. It is the methodology's narrow-don't-collapse move done right. One nit: the review asserts MMP is "the strongest deployment claim among the recent works" and "running, but in the authors' own reference implementations, not verified commercial third-party adoption." That hedge is good. But the review states this *twice* (§intro-adjacent and §conclusion and the references entry) — three times total. Once is enough.

The MMP comparison is the strongest part of the review. No substantive finding against it.

### The MAIF treatment — accurate

Verified against arXiv:2511.15097. MAIF's abstract (verbatim): "an artifact-centric AI agent paradigm where behavior is driven by persistent, verifiable data artifacts rather than ephemeral tasks," with "the Multimodal Artifact File Format (MAIF), an AI-native container embedding semantic representations, cryptographic provenance, and granular access controls," motivated by "regulatory barriers" and "emerging regulations like the EU AI Act." The review's differentiation — "MAIF fuses verification; the plan fuses agency" — is **accurate.** MAIF is a container format for auditable/trustworthy data; it has no negotiation, no wants. The review correctly forces the plan to drop any claim on the *phrase* "artifact-centric." Good. No finding.

One small accuracy point in the review's favor and one against: the review says "MAIF has no conflict-resolution mechanism, no peer-to-peer negotiation between artifacts." Correct from the abstract. But the review's claim "Its artifacts *prove*; they do not *act*" is a touch rhetorical — MAIF's "active trust enforcement" does mean the artifact carries access controls that *gate* operations, which is a (narrow, deterministic) form of acting. Minor: soften "they do not act" to "they verify and gate; they do not negotiate or self-maintain."

### The "keep the framing" decision — holds, except §(c)

Covered in SUBSTANTIVE-4. The framing is kept defensibly for three of the four bold moves. The one place keeping-the-framing shades into overclaim the prior cycle missed is conclusion §(c)'s "genuinely new" — given the blackboard revival and Agora, that absolute does not survive a 2026 walk. Narrow it; don't collapse it.

### The cost-stratification "bet with hedge" — honest, but cite the bullish number too

Covered in SUBSTANTIVE-5. The rewrite genuinely engages the economics — the "watchers redoing cheap-tier proposals is a throughput cost the bet has to absorb" sentence is the honest move and is not hand-waving. The remaining flaw is selective citation: the review uses "Drop the Hierarchy"'s threshold finding (bearish) and omits its 95%-quality-at-24x-cheaper finding (bullish), from the *same paper*. Add the bullish number; state the residual uncertainty as "benchmark-near-capable ≠ negotiation-capable." Then it is fully honest.

---

## Findings table

| # | Block | Type | Severity |
|---|---|---|---|
| SUBSTANTIVE-1 | 1 / walk | substantive | high — missing prior art (blackboard revival) |
| SUBSTANTIVE-2 | 1 / walk | substantive | medium — missing prior art (Agora) |
| SUBSTANTIVE-3 | 1 / walk | substantive | medium — missing prior art (InfiAgent line) |
| SUBSTANTIVE-4 | 1 | substantive | medium — overclaim in §(c) |
| SUBSTANTIVE-5 | 1 | substantive | medium — selective citation |
| SUBSTANTIVE-6 | 1 | substantive | medium — unconfronted contradiction |
| STRUCT-1..4 | 2 | structure | low-medium |
| ACCESS-1..8 | 3 | accessibility | medium (load-bearing block) |
| PROSE-1..6 | 4 | phrasing | low |

6 substantive, 17 structure/accessibility/phrasing.

---

## Appendix — What prior cycles missed

(Written after the independent review, by scanning `REVIEW_CYCLE_1_LIVING_ARTIFACTS.md` and the response files.)

Cycle 1 was thorough on MMP, MAIF, CodeCRDT, SwarmSys, "Drop the Hierarchy," Semantic Consensus, and the framing narrowings — and the MMP point-by-point comparison and the cost-stratification "bet with hedge" are direct, well-executed products of Cycle 1's findings and the MMP addendum. Credit where due: the hardest narrowing (MMP) was done correctly.

What Cycle 1 and its response missed, that this cycle surfaces:

1. **The blackboard revival (SUBSTANTIVE-1).** Cycle 1's walk treated the four classical coordination systems as static history and walked only the *recent LLM-agent* seeds forward. METHODOLOGY 5b requires walking *every* seed both directions. The "blackboard" seed walked forward lands directly on arXiv:2507.01701 and arXiv:2510.01285 — a live 2025-2026 program building exactly "LLM blackboard without a controller." Cycle 1's seed list should have caught this; it is the audit-trail failure METHODOLOGY 5a is designed to expose.

2. **The file-centric-state line (SUBSTANTIVE-3).** Cycle 1 (and §8's "missing abstraction" framing) treated "between-sessions first-class artifact" as the plan's space. InfiAgent (Jan 2026) and "Everything is Context" (Dec 2025) make file/artifact-as-authoritative-state a converged research pattern. Missed because the walk did not run the "agentic file system / externalized state" topic cluster.

3. **The selective citation of "Drop the Hierarchy" (SUBSTANTIVE-5).** Cycle 1's cost-stratification rewrite leaned on the paper's threshold finding and never noticed the same paper supplies the bullish 95%-at-24x number. A response cycle re-reading the source (METHODOLOGY step 4) should have caught both halves.

4. **The "intelligent conflict resolution is genuinely new" overclaim (SUBSTANTIVE-4).** Cycle 1's "keep the framing" decision was defensible but did not pressure-test conclusion §(c)'s absolute against 2026 work; Agora and the blackboard papers make "genuinely new" indefensible as written.

5. **Accessibility was under-weighted.** Block 3 is load-bearing per METHODOLOGY, and Cycle 1 appears to have treated the review's intro term-list as discharging the obligation. It does not — the review uses "convergence," "semantic/syntactic," "first-class," "superposition," and a drift of acronyms (OT, EA, CMB, SVAF) load-bearingly across 13,000 words without re-anchoring. A load-bearing block needs the hard pass ACCESS-1..8 gives it.

Cycle 3 should: walk every classical seed forward (not just backward); run the "agentic file system," "LLM blackboard," and "decentralized debate" topic clusters explicitly; and re-check May-2026 arXiv for anything landing closer than the blackboard papers.
