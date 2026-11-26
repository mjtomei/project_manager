# Review Cycle 6 — Literature Review: Living Artifacts

**Reviewer:** Fresh adversarial pass, blind to prior cycles at time of drafting.
**Artifact:** `pm/docs/literature-review-living-artifacts.md` (~11,060 words).
**Date:** 2026-05-15.
**Convergence question:** Is this document DONE?

---

## Top-line verdict

This document is in good shape. The substance is defended carefully, the prior-art comparisons are precise, the contribution claim is narrowed rather than collapsed, and the four sub-claim narrowings in "Read on the framing" are honest. I went in expecting to find at least one genuine substantive miss after five cycles. I did not. What I found is a small set of phrasing and accessibility findings, one genuine structural finding (the "prior art in brief" section's relationship to Appendix B), and a verbosity pass that recovers maybe 350-450 words.

**Verdict: CONVERGED.** Details below. The remaining findings are real but minor; none is load-bearing enough to justify another full cycle. The methodology's stopping rule ("stop when findings get pedantic") is satisfied. I recommend a single light apply pass for the Block 3/4 items and the verbosity cuts, then stop the loop.

---

## Block 1 — substance

### 1.1 (Minor) The MMP "production" claim is hedged in the references but stated flatly in the body

Body, Introduction: "The **Mesh Memory Protocol** (MMP, arXiv:2604.19540) specifies and runs a typed, semantically-merged, cross-session shared memory for LLM agents." The word "runs" implies a deployed system. The reference entry correctly hedges: "running, but in the authors' own reference implementations, not verified commercial third-party adoption." The body should carry the same hedge — change "specifies and runs" to "specifies and demonstrates in its own reference implementations." This is a one-word-cluster fix, not a substantive error, but the body is where most readers stop.

### 1.2 (Not a finding — verified) Citation-graph walk found no preempting prior art

See the dedicated section below. I checked four 2026 candidates that did not appear in the references (Autogenesis 2604.15034, Self-Evolving Software Agents 2604.27264, Coordination-as-Architectural-Layer 2605.03310, EngiAgent 2605.02289). None preempts the plan; all are agent-centric. The closest, Autogenesis, is the nearest miss and is discussed below — but it does not require a contribution narrowing, only an optional one-sentence cite. This is a convergence signal.

### 1.3 (Minor) "Coverage gaps in this review" is the strongest section and is slightly buried

The bulleted coverage-gaps list is the most intellectually honest part of the document and the thing a critical reader most wants. It currently sits after "Read on the framing" at the tail of the conclusion, before References. It is fine where it is, but consider promoting one sentence of it into the executive summary — the exec summary currently sells the "bet is supported" verdict without flagging that four named things are untested. A reader evaluating the bet deserves to see the open risks before the appendices. One sentence: "Four elements remain untested — see Coverage gaps." No substantive change, just signposting.

### 1.4 (Checked, no finding) The determinism/central-scheduler narrowing is correct

B§1's claim that "central scheduler" is false for actors, contract-net, and Linda and true for classic blackboards is accurate. The actor model has no scheduler; contract-net is announce-bid-award with no master; Linda's tuple space has no scheduler; Hearsay-II/blackboard had a central control component. This is correct as written. No finding.

---

## Block 2 — structure

### 2.1 (Genuine, minor) "Prior art in brief" duplicates Appendix B's section headers with near-zero added information

The "Prior art in brief" section is eight bullets, each ending "Full treatment in Appendix B §N." Several bullets carry only the cluster name plus a list of system names already named elsewhere — e.g. the "Evolutionary computation" bullet is one sentence listing five systems, all of which reappear in B§6, and the executive summary already gestures at the survey's shape. This section is a table of contents wearing prose clothes. Two options: (a) cut it to an actual short list / table ("Cluster — closest 2026 work — Appendix"), which is faster to scan and honest about being a map; or (b) keep it but make each bullet earn its place by stating the *one-line verdict* for the cluster (does it preempt? yes/no/partly), which the bullets currently mostly omit. Option (a) saves ~150 words. This is the one structural finding worth acting on.

### 2.2 (No finding) Section flow

The body flows well: exec summary → what the plan proposes → what surrounds it → four instances → prior art in brief → conclusion. The four-instance section is genuinely the most concrete and is correctly placed early. The ASCII diagram in the conclusion is well-used. No abrupt transitions found.

---

## Block 3 — non-expert accessibility (load-bearing)

This block is where a near-converged document is most likely to still have debt, because accessibility fixes get deprioritized against substance. I found it mostly clean — the document glosses aggressively up front (PR, artifact, LLM, negotiation, plan, project.yaml, watcher, first-class, superposition all defined inline). A few remain.

### 3.1 (Genuine) "DAG" is glossed once, late, and used earlier unglossed

"DAG" first appears in the executive-summary-adjacent body? No — first load-bearing use is B§4 ("adaptive DAG"). It is finally glossed in B§5's AgentNet bullet: "a dynamically restructured DAG — a dependency graph with no cycles." But B§4 uses "adaptive DAG" with no gloss, and B§4 comes first. Move the gloss to first use in B§4, or gloss both. Target reader does not know "DAG." One-clause fix: at B§4's "adaptive DAG," write "adaptive DAG (a dependency graph with no cycles)."

### 3.2 (Genuine) "CRDT" / "operational transformation" — the acronym is spelled out but the concept stays abstract for the target reader

B§2 spells out "conflict-free replicated data types" and "operational transformation" and even gives the Google Docs anchor for OT, which is good. But CRDT is then used a dozen times as a bare acronym across B§2 and B§4. For the target reader, a dozen "CRDT"s after one definition is acronym creep. This is acceptable if the definition is memorable — and "the modern, decentralized answer to the problem OT solved with a central server" is reasonably memorable. Borderline; I would leave it. Noting it only so the apply pass can decide. Not a required fix.

### 3.3 (Genuine) "stigmergy" / "stigmergic" used three times; glossed well once, but the adjective form lands before some readers anchor it

B§5 defines stigmergy cleanly ("indirect coordination... ants laying pheromone trails"). Good. But the "prior art in brief" cluster and the executive-summary region do not use it, so the definition-before-use ordering is actually fine here. No fix needed — flagging only to confirm I checked.

### 3.4 (Genuine, small) "min-cut" in the MEMOREPAIR sentence is unglossed jargon

B§5: "MEMOREPAIR... solves it exactly with a centralized provenance min-cut." And the reference entry: "a centralized, deterministic provenance min-cut." "Min-cut" is graph-theory jargon the target reader will not know and it is doing real work in the sentence (it is the contrast against the plan's decentralized approach). Replace with a plain-language gloss: "...solves it with a centralized, deterministic recomputation that traces every downstream artifact and repairs it in one pass." That conveys the contrast (centralized + deterministic + closure-style) without the term. The word "min-cut" adds nothing the target reader can use.

### 3.5 (No finding) "Why should I care?" check on section openings

Spot-checked: the four-instance section opens "This section is the most concrete in the review" — good, names the benefit. B§2 opens with a question ("Can many edits happen to one document at the same time without a referee...") — good. B§6 opens "The plan makes one ambitious side-claim" — good. The openings pass.

---

## Block 4 — prose

The prose is tight. The document has clearly been through copy-edit passes. A handful remain.

### 4.1 (Genuine) Garbled sentence in the executive summary

Line 11: "What the plan builds, in plain terms is set out in the Introduction's 'What the plan proposes.'" This sentence is missing a comma and reads as broken. It is also a pure pointer with no content — it tells the reader to go read another section. Either cut it entirely (the exec summary does not need a forward-pointer to the very next major section) or fix it: "What the plan builds, in plain terms, is set out in the Introduction below." I recommend cutting it — it is deadwood, ~12 words.

### 4.2 (Genuine) Stacked parenthetical in the "What surrounds the plan" paragraph

Line 50: the paragraph ending in "...what is new is that large language models make it buildable" contains a 60-word parenthetical mid-paragraph: "('First-class' is a programming term used below: it means the half-finished... not bolted on as an afterthought. The plan also speaks of proposals in *superposition*...)." A parenthetical containing two sentences and a second glossed term is no longer a parenthetical; it is a paragraph hiding in parentheses. Pull it out into its own short glossing sentence-pair after the paragraph, or fold "first-class" and "superposition" into the up-front glossary block in the Introduction where the other terms already live. The Introduction already has a glossary block — these two belong there, not mid-flow in the prior section.

### 4.3 (Minor) "very" and intensifier check

Searched for intensifier creep. "very recent" appears twice (coverage gaps, B§1). Both are defensible — they flag preprint recency, which is load-bearing. No cut. "genuinely" appears 2-3 times; acceptable. Emphasis density (italic/bold) is moderate and mostly load-bearing. No finding.

### 4.4 (Minor) Repetition of the "relocated, not eliminated" formula

The phrase "adjudication is not eliminated — it is relocated" and close variants appear at least five times: Introduction claim 2, Instance 3 "what it enables," conclusion (c), conclusion (d), "Read on the framing." This is the document's central honest move, so *some* repetition is correct emphasis. But five is one or two too many — the Instance 3 statement and the conclusion (d) statement say the same thing in nearly the same words within a few hundred words of each other. Keep the Introduction statement and the conclusion (d) statement (the fullest one); trim the Instance 3 and conclusion (c) restatements to a back-reference. Saves ~60 words and stops the formula from going numb through overuse.

---

## Citation graph walk (Step 5 — mandatory)

**Seeds (8), chosen as the most load-bearing references:**

1. AgentNet (arXiv:2504.00587) — the "closest built decentralized coordination" anchor.
2. CodeCRDT (arXiv:2510.18893) — the semantic-residue evidence.
3. Mesh Memory Protocol (arXiv:2604.19540) — declared the single closest prior art.
4. "Drop the Hierarchy and Roles" (arXiv:2603.28990) — the 25,000-run empirical anchor.
5. MAIF (arXiv:2511.15097) — the "artifact-centric paradigm" precedent.
6. ScienceClaw + Infinite (arXiv:2603.14312) — closest self-maintenance analogue.
7. Ψ-Arch (arXiv:2604.13934) — autopoietic / self-constructing-software anchor.
8. Externalization survey (arXiv:2604.08224) — the file-as-state umbrella.

**Walk method:** Forward (papers citing each seed) and backward (each seed's references), plain web search plus arXiv listing, date-restricted to the last ~12 months with attention to Feb–May 2026. ~45 minutes.

**New work surfaced (4 candidates, all checked):**

- **Autogenesis: A Self-Evolving Agent Protocol (arXiv:2604.15034, Apr 2026).** Closest of the four. Abstract: "...existing agent protocols (e.g., A2A and MCP) under specify cross entity lifecycle and context management, version tracking, and evolution safe update interfaces..." It proposes a Resource Substrate Protocol Layer (prompts/agents/tools/memory as versioned registered resources) and a Self Evolution Protocol Layer — "a closed loop operator interface for proposing, assessing, and committing improvements with auditable lineage and rollback." **Verdict: does not preempt.** Autogenesis treats resources as registered, versioned entities under a protocol; the evolution loop is an operator interface, not peer-to-peer negotiation between artifacts, and the resources carry no wants. It is *adjacent* to Instance 3 (pm's orchestration becomes the artifact protocol). Optional one-sentence cite in B§4 alongside the Externalization survey: it is one more 2026 data point that "lifecycle/versioning as a substrate concern" is being built — it reinforces, not threatens, the plan. Not required for convergence.
- **Self-Evolving Software Agents (arXiv:2604.27264, Apr 2026, AAMAS extended abstract).** Abstract: combines "BDI reasoning with LLMs to enable autonomous evolution of goals, reasoning, and executable code." **Verdict: does not preempt.** Agent-centric (the *agent* evolves its goals); the plan puts agency in the artifact. It belongs, if anywhere, in B§6 next to A-Evolve as another "single-system self-improvement, not a population negotiating its own selection" data point — and B§6 already makes that exact point with A-Evolve and CORAL. No cite needed; the slot is full.
- **Coordination as an Architectural Layer (arXiv:2605.03310, May 2026).** Argues coordination should be a configurable architectural layer separable from agent logic; cites the 41–87% multi-agent production-failure figure. **Verdict: does not preempt.** The 41–86.7% figure is already in the document via Semantic Consensus (B§5) and the "Read on the framing" tension note. This paper is a foil, not prior art — it keeps coordination as a *layer over agents*, which is the design the plan argues against. No cite needed.
- **EngiAgent (arXiv:2605.02289, May 2026).** Fully-connected coordination of LLM agents for engineering problems. **Verdict: does not preempt.** Agent-centric, domain-scoped. No cite.

**Coverage report:** Forward and backward walk on all 8 seeds. The four newest candidates (all Apr–May 2026, all post-dating earlier drafts) are agent-centric coordination/evolution papers. **None preempts the plan's artifact-centric, agency-in-the-artifact contribution.** The plan's residual contribution — agency, wants, and self-maintenance located *inside* a general artifact substrate, proven in a working tool — survives the walk untouched. The single optional addition is a one-sentence Autogenesis cite in B§4; it strengthens the plan's lineage and is not a narrowing. **This is a strong convergence signal: a 45-minute walk over 8 seeds in the most active possible subfield found zero preempting work.**

---

## Verbosity pass (Step 10 — standing, every cycle)

Read the full ~11,060-word document start to finish hunting text verbose relative to its point.

**Findings (estimated ~350–450 cuttable words):**

- **Line 11** — the garbled "What the plan builds, in plain terms is set out..." pointer sentence. Cut entirely. ~12 words. (Block 4.1.)
- **Line 50** — the 60-word mid-paragraph parenthetical glossing "first-class" and "superposition." Not a pure cut, but moving it to the Introduction glossary block removes ~30 words of connective scaffolding ("is a programming term used below," "The plan also speaks of"). ~30 words.
- **"Prior art in brief" section** — converting eight prose bullets to a scan-table or trimming the content-free ones removes ~150 words. (Block 2.1.)
- **The "relocated, not eliminated" formula** — appears 5×; trimming two restatements to back-references saves ~60 words. (Block 4.4.)
- **B§4 AutoGen/MetaGPT/ChatDev block** — these three are described, then "So the plan is correct that the mainstream... is orchestrator-centric" restates the obvious conclusion. The three bullets already make the point; the summary sentence and the following sentence partly overlap. ~25 words recoverable by merging.
- **Conclusion (a)** — "Nothing in the aspiration is unprecedented. Engelbart's NLS imagined... blackboard systems imagined... the actor model imagined... Linda tuple spaces imagined..." is a four-clause parallel list that B§1 and B§3 already cover in full. The conclusion can compress this to one sentence ("The aspiration is assembled from parts — NLS, blackboards, actors, tuple spaces — that have been in the literature for decades") and drop the per-system "imagined" clauses. ~50 words.
- Scattered hedge/deadwood: a handful of "turns out to be," "worth a precise comparison," "worth stating with care" — ~20 words across the document.

**Verbosity verdict:** The document is *mostly* tight — this is not a 16,000-word bloat situation; it is an 11,060-word document with ~400 words of recoverable slack, most of it in two spots (the "prior art in brief" ToC-section and the conclusion (a) parallel list). The apply pass should net-cut. After cuts the document lands around 10,650 words. This is a near-convergence signal: the cuts are real but small and localized, not systemic.

---

## Convergence verdict

**CONVERGED.** Stop the loop.

Reasoning: Six cycles in, this pass produced (a) zero substantive prior-art misses despite a full 8-seed bidirectional citation walk in the most active subfield in AI; (b) one genuine structural finding (the "prior art in brief" ToC-section); (c) a small set of accessibility fixes (DAG gloss, min-cut gloss); (d) a handful of prose fixes (one garbled sentence, one over-long parenthetical, one over-repeated formula); and (e) a verbosity pass recovering only ~400 words from an 11,060-word document. None of these requires another reviewer cycle — they are an apply-pass checklist. The contribution claim is correctly narrowed and well-defended. The methodology's stopping criteria ("findings get pedantic," "citation walk finds nothing," "verbosity pass finds little") are all met simultaneously. One light apply pass, then ship.

---

## Appendix — what prior cycles missed

(Scanned after the independent review above was drafted: REVIEW_CYCLE_1–5_LIVING_ARTIFACTS.md and the response files.)

After scanning the five prior cycles and their responses, my assessment:

- **The prior cycles were thorough and converged honestly.** Cycles 1–5 surfaced the MMP comparison, the determinism/central-scheduler narrowing, the persona-prompting grounding, the evolutionary-computation narrowing to "negotiated internal selection," and the 2026 cluster (Agora-Opt, Semantic Consensus, Consensus Trap, MEMOREPAIR, CORAL, Ψ-Arch, First-Class Intermediate Artifacts, LSS). The document I reviewed already reflects all of these. The loop did its job.
- **Nothing substantive was missed.** My citation walk found four newer (Apr–May 2026) papers no prior cycle could have seen because they post-date earlier drafts — but all four are agent-centric and none preempts. So even the "newest possible miss" category is empty. This confirms the prior cycles' convergence rather than contradicting it.
- **What prior cycles under-weighted (minor):** the accessibility debt I flag in 3.1 (DAG) and 3.4 (min-cut) appears to have survived all five cycles — small jargon items that each cycle's substance focus let slide. Block 3 is load-bearing and these are exactly the "jargon a working engineer uses without thinking" the methodology warns about. They are tiny, but they are the kind of thing the loop is structurally biased to miss, and five cycles did miss them. Worth the apply pass.
- **The garbled sentence on line 11** also survived five cycles — a sign the verbosity/prose passes were focused on additions rather than re-reading original-draft prose start to finish, exactly the failure mode Step 10 exists to catch.

These are apply-pass items, not new-cycle items. The prior cycles' overall judgment — that the document is converging — is correct, and Cycle 6 confirms it.
