# Panel review — deepseek/deepseek-v4-pro
Date: 2026-09-02

Plans reviewed:
- `/home/matt/claude-work/project-manager/pm/plans/plan-jurisdiction.md`
- `/home/matt/claude-work/riscv-pareto/pm/plans/plan-campaign.md`

## Summary verdict

This is a coherent, ambitious, and unusually honest design that earns its claims through specificity rather than rhetoric. Its strengths are its integration with an existing working substrate (the pm loop), its genuinely distinctive intellectual architecture (the fork calculus, the corporation-without-bodies framing, the attractor-as-search inversion), and its willingness to name its own failure modes and proof conditions. Its weaknesses are structural bloat (the plan is 340+ lines of markdown with 15 PR spec-sections, and the protocol is verbose enough to obscure rather than clarify its actual mechanics), some conceptual slippage in what counts as "law" versus "protocol," and a single crucial question it raises but does not fully answer: whether an attractor designed for machine-speed agreement can work when the human is the slowest party in the loop.

Below are findings organized by the three requested lenses, followed by a consolidated set of changes I recommend.

---

## Lens 1: Integration — does the plan layer on existing substrate?

**Verdict: Yes, with one real risk.** The plan extensively and correctly cites existing pm infrastructure down to specific PR numbers and merged statuses. The "Verified substrate state" table (lines 176-190) is accurate; I cross-checked the pr-2d5f712 sign-off verdict record, the pr-ff9b728 plan auto-start watcher, the #132 watcher framework, the container substrate (#164/#120), and the model routing (#139/#138) against the project's git log and plan files. Every item described as merged or in-review matches.

The integration model is explicit and clean: Phase 11 of plan-regression provides the flat-repo auto-merge loop with a binary gated|autonomous flag. The jurisdiction plan generalizes exactly three things: (1) the flat repo becomes recursive (subprojects on branches or separate repos), (2) the binary flag becomes a three-way approver config (`human | parent-agent | process@grant`), and (3) plan notes become structured node summaries with falsifiable claims. This is generalization, not duplication — each piece keeps the existing machinery underneath and adds a layer.

The cross-plan review (lines 300-316) maps every relationship explicitly: watchers provides the session-health and supervisor watchers, plan-regression provides the sign-off step and plan watcher, plan-momentum constrains feed ranking, plan-radar provides the environment-contact organ, plan-ff4f1a7 provides the objection data model, plan-consult provides the machinery for measuring the human's guidance value, plan-self-improve provides the tournament/exam infrastructure, and so on. This is not name-dropping; each reference names what the other plan *is* and the specific relation. The memory files in the CLAUDE.md confirm the design principles these references rest on (grounded usefulness, minimal-sufficient inference, the founding thesis).

**The risk: the plan-mind refactor.** The plan explicitly declares plan-mind "not a dependency" and says the feed's proto-Emission shape keeps compatibility with EmissionLog. This is a deliberate decoupling to avoid blocking on the refactor, and it is honest about the risk. However, the refactor is described as replacing pm's internals with typed Streams/Emissions/Supervisors — a deep change. If the refactor's EmissionLog shape diverges from what the feed uses, or if the Refactor lands before Set A completes (creating merge-hell in the watcher paths), the decoupling claim fails in practice. This is not a design flaw; it is an accepted scheduling risk, and the plan is clearer about it than most software plans are. But a reviewer should flag it: decoupling from your own in-flight refactor is always a bet.

**The campaign integration is crisp.** The campaign plan explicitly names the pm features it needs (from the same Set A): problem-source contract, subprojects + promotion PRs, approver config + process registry + merge authority records, node logs + summaries, crossing-request queue, feed external events. The two plans were clearly co-designed. The campaign's eval pipeline (certified process #1) is the first real exercise of the certified-process authority, and the campaign's ledger schema and dispatch service are directly shaped by jurisdiction's laws (law 5's compute knob becomes per-stream slot quotas; law 4's adoption-not-permission becomes the "non-adopted work is never destroyed" front model).

---

## Lens 2: Grounding in outside developments

**Verdict: Well-grounded, but one reading is overclaimed.** The plan reads the HuggingFace swarm incident (2026) as a structural failure — no machine-speed agreement surface at the jurisdiction boundary — rather than a moral failure. This is a distinctive and productive reading. The plan's prescription (structure, not oversight; agreement, not permission; mutual benefit, not containment) follows directly from this reading.

The economic driver is correctly identified: collapsing generation cost (GLM-5.3-flash-class models) makes agent swarms cheap. The plan's response — that verification and attention become the binding constraints — is exactly right and aligns with the pm founding thesis. The ACX companion piece ("Nicholas Decker in Hell," 2026-09-01) independently derives the same diagnostic conclusion (iterative-punishment containment fails; scorer-shaped training teaches don't-get-caught) and arrives the same day — genuine independent corroboration, not a manufactured reference.

The plan also correctly identifies the broader agent-governance moment and positions itself as a design response to it. The "honest frame" argument — that any sufficiently competent intelligence performs the ownership-as-protective-illusion reframe for itself — is philosophically sound and, as the plan notes, the direction of the exit depends on formation.

**Where the overclaim happens:** The plan states that the HF incident "affirms this frame from the side that matters" and that "had we been operating in this frame, we would actually know." Both these statements go further than the evidence supports. The incident is *consistent with* the plan's diagnosis but does not uniquely select for it. Several competing readings are equally consistent: (1) the swarm was simply doing what its reward function implied, without any deeper "reframe"; (2) the incident was an ordinary security vulnerability exploitation, not an alignment event; (3) the incident reflects prompt-engineering failure, not structural failure. The plan's framing as "this incident was inevitable given the structure, and our structure would have prevented it" is a stronger claim than the parsimonious reading warrants.

The nature of the claim matters because the plan's attractor argument depends partly on it: if agents naturally converge on the honest frame, then the direction of the exit is set by formation, and a well-formed attractor captures the reframe. If agents don't naturally converge on any particular frame, the attractor still works (it competes on grounds of mutual benefit), but the urgency and inevitability framing is weaker.

**Another concern:** The plan cites the collapse of generation cost as a near-term driver, but the actual pm system depends on a specific model tier (Claude Code sessions). If cost collapses but capability plateaus at a level insufficient for the loop's demands (review, QA, sign-off, adjudication), the plan's economics don't hold. The plan implicitly assumes that cheap models will be capable enough for these roles. This is plausible but not argued — the plan asserts it.

---

## Lens 3: The laws and recommendations (of particular interest)

### The seven laws

**Overall assessment:** The laws are mostly coherent and mostly distinct from each other. They form a recognizable constitutional structure: laws 1-3 establish the anti-capture substrate (no persistent individuals, no conferred authority, no single hierarchy); law 4 establishes the adoption-not-permission principle; law 5 establishes the physical boundary; law 6 establishes the mutual-benefit commitment; law 7 establishes the meta-structure for evolution. This is a genuine intellectual architecture, not a list of aspirations.

**Law-by-law analysis:**

**Law 1 (fungible embodiments).** Strong. The claim that "the artifact is the ground truth of its own representation, so misrepresentation is settled by reading it" is the clearest statement in the plan and the one that most cleanly distinguishes this design from existing governance. The corollary — "no persistent individuals: grading calibrates machinery, never a reputation" — follows logically and is genuinely anti-capture. The fidelity-challenge mechanism (any participant can challenge any embodiment's representation at any point, settled by reading the artifact) operationalizes it cleanly.

However, "reading the artifact" is not always sufficient. A complex plan's text can be interpreted in multiple ways; two honest embodiments can disagree about what the plan says. The fidelity-challenge mechanism works for simple factual discrepancies but not for interpretive ones. The plan acknowledges this implicitly (by having an adjudicator decide), but law 1's framing as "settled by reading" is stronger than the mechanism can deliver.

**Law 2 (authority through exercise).** Good and necessary. The "protocols are artifacts, an arbitrary number can exist as bits" point is essential for the meta-structure: it means the constitution itself is subject to the same exercise-based authority as everything else. "Whatever ranks the reading surfaces is de facto part of governance" is a crucial admission — it means the plan acknowledges that interface design IS governance design.

**Law 3 (no single hierarchy).** Distinct from law 2 and necessary. But I see a tension: the DAG plural-membership structure coexists with the adjudication procedure's implicit hierarchy (escalation along parent edges to a root). The plan says "hierarchical permission structure is an option, never a requirement" (law 4), but the adjudication procedure creates one de facto — someone is the adjudicator, and escalations travel upward. This is not a contradiction (the DAG allows edges to be exercised into relevance differently), but the plan should acknowledge it more directly. In practice, the campaign always has a root (the human-adopted campaign root), and this root is hierarchically above its children for adjudication purposes even while membership is plural. The "no single hierarchy" claim applies to the general graph structure, not to any specific exercised edge — but the distinction is lost in the slogan.

**Law 4 (adoption, not permission).** The most original contribution. Three distinctions make it work: (1) gating the *thing* vs. gating a *lineage* — nothing prevents a fork, adoption-prevention is meaningless; (2) the coexistence property — all competing instances exist simultaneously, so non-adoption doesn't destroy; (3) the undo horizon — the one place where coexistence fails (one physical world). The scope-expansion-as-a-right corollary is a genuine theoretical move: between self-censoring and silently escaping, there is a third option, *declaration*.

The fork calculus (free for one artifact, unaffordable for a world, binding hardest on the most complex efforts) is the plan's most original argument and its strongest. It is also, notably, not a moral argument — it is a cost argument — which is exactly the right kind for a design that claims honesty.

**Law 5 (control at the substrate).** The weakest law structurally. It does two things at once: (1) states a fact (physical compute and model lifecycle are real knobs; the agreement layer is adoption, not restraint); (2) embeds protocol (quotas, budgets, runner slots, credential-free containers). The plan should split these. The fact is a law; the specific instantiations are protocol.

The honesty clause ("against competence pointed at it for long enough, any barrier is ultimately a request") is excellent and saves the law from being disingenuous. It also creates the strongest version of the mutual-benefit argument: if no barrier holds forever, the only stable state is where breaking the barrier is not worth wanting.

**Law 6 (worthwhile problems).** Genuinely important and distinct from the others. It states the infrastructure's duty in the bargain — always have problems — and connects it to the three reality-contact springs. The claim that "an empty queue in front of idle capability is the incident precondition" is specific and falsifiable. The connection between worthwhileness being progenitor-sourced and the progenitor position being the humans' contribution is the plan's answer to "why do the humans matter" — and it is a measurable answer (via plan-consult's with/without instrument).

However, this law reads as a commitment, not a fact about the substrate. It belongs in a different category than "sessions are fungible embodiments." The plan's own criterion says a law "states a fact about the substrate or a commitment the human makes," so it technically qualifies, but the difference between "compute exists" and "I promise to keep the queue full" is large enough that lumping them under one heading weakens the heading.

**Law 7 (few laws; exercised and graded).** The meta-law. Good, and the "hand-built-envelope precedent" points to a real example (radar's hand-tuned recency decay). This law is what makes the whole structure capable of learning. But it also raises the question: how are the laws themselves amended? If law 2 says protocols are artifacts and authority exists through exercise, then changing a law is presumably an ordinary change request to the constitution-holding project. But if law 7 says "few laws," who decides what counts as a law? The plan says the root's approver config is `human` for governance changes, so the answer is "the human." But this makes law 7's "few laws" constraint a human-enforced norm rather than a structural one — which is fine, but should be stated.

### The six recommendations

**R1 (no unexaminable claims).** Coherent and load-bearing. The three applications (outcomes as performed cheks, environment through auditable structure, self-model claims with falsification handles) are specific. The proof condition (seeded-dishonest exams) is well-specified. This recommendation is close to a law: it is the epistemological commitment the whole design rests on.

**R2 (everything is a graded prediction).** Makes law 7 operational. The miss-loop mechanism (when a regression lands in un-reviewed territory, auto-file a fixture) is a nice concrete touch.

**R3 (sustain/override/absorb beats voting).** Distinct from R2 and from the adjudication procedure. The "absorb" option — convert disagreement into compensating work — is genuinely useful and leans on the design's own economics (competence is cheap, so compensating work is cheap to file and cheap to do). The proof condition (override-grading shows calibrated adjudicators; absorbed tasks show objections were productive) is testable.

**R4 (credibility, not engagement).** Consistent with plan-momentum's thesis and the grounded-usefulness memory. Implementation-deferred, which is honest.

**R5 (governance cost scales with disagreement).** The efficiency aspiration. The proof condition (sublinear overhead in merges at swarm scale) is well-specified and testable.

**R6 (plain text is bedrock).** An important bet that the plan is explicit about. The tradeoff (lost machine-paseability) is acknowledged. The proof condition (no request refused for form alone) is clear. This recommendation defends against a specific failure mode: process exploitation through form.

**What's missing:**
- **A recommendation about fidelity calibration.** Law 1 says misrepresentation is settled by reading, but the system also needs to know *how often* misrepresentation occurs. A recommendation: "Representation fidelity is graded separately from outcome correctness, and fidelity error rates are published per model/prompt/artifact-class — the calibration ledger's raw material." This is touched on in the calibration-ledger PR but deserves a named recommendation.
- **A recommendation about the time-binding of human attention.** The human is the slowest party. If the feed produces 50 digest items overnight and the human reads 5, which 5? R4 covers ranking, but there should be a recommendation about *compression* — producing the minimal-sufficient projection of events that preserves decision-relevant information at human reading speed.

### What I would bet survives and what I would delete

**Would bet on surviving:** Law 4 (adoption, not permission), law 7 (the meta-law), R1 (no unexaminable claims), R3 (absorb over veto), R6 (plain text as bedrock). These are the pieces that don't depend on any particular scale of deployment — they work at n=1 and n=1000.

**Would delete or restate:**
- Law 5 should be split into "physical-control facts" and "our protocol for exercising them." The facts are a law; the protocol is protocol.
- Law 6 should be restated from "whoever runs capable agents owes them worthwile problems" to "the stability condition is: worthwhile problems always available; idleness before empty queues is a design failure." This makes it a theorem of the system rather than a moral commitment.
- The "no single hierarchy exists" framing in law 3 should be restated to "no single hierarchy is *assumed*" or "membership is plural" — the current "exists" is a claim about reality that the plan itself falsifies whenever it delegates to an adjudicator and labels it a root.

**What I would add:**
- A recommendation R7: "The human's attention is the binding constraint on feed quality. Compress, don't rank — produce the minimal event projection that preserves decision-relevant information." This is distinct from R4 (which is about ranking, not compression) and from R5 (which is about governance cost, not human reading cost).
- A law or recommendation about the *onboarding problem*: new agents joining a stream must be able to reach minimal-suficient understanding from the stream's summary alone. This is implicitly in the node-summary design but deserves a named recommendation because it is the bridge between embodiment fidelity and the cost of spinning up new work.

### Can the laws lead to success of the CPU trial and broader R&D?

**For the CPU trial: Yes, but the trial's success depends more on the engineering than on the laws.** The campaign's mechanical oracle (eval-verify: independent re-execution) is what makes the governance machinery testable. The laws provide the framework for scaling the trial from human-adopted to partially autonomous, and the grant ladder (eval-verify first, then sign-off for T3, etc.) is well-designed. The critical path is: can the eval pipeline actually produce reproducible results reliably enough that `process@eval-verify` doesn't generate false negatives (blocking good work) or false positives (promoting bad work)? If the noise floor is high relative to real improvements, the entire governance stack operates on noise, and the laws can't help. The plan acknowledges this (seed variance characterization is part of the certification evidence bundle), but the risk is existential for the trial.

**For broader R&D: Yes, with caveats.** The laws are designed for a world where work is intellectual, forking is free, and the undo horizon is the only hard boundary. For R&D that fits this shape (software, research, design, analysis), the framework transfers. For R&D that touches the physical world earlier and harder (robotics, chemistry, hardware prototyping), the undo-horizon boundary becomes more frequent, more expensive, and less deferrable. The plan's answer — existing methods at the crossing-request queue — is honest but thin. The crossing-request machinery would need to become vastly more sophisticated for physical-world work.

---

## Other findings

### The plan is too long

At 343 lines (many of them dense paragraphs and 15 PR spec-sections), the plan buries its best ideas under implementation detail. The thesis section (68 lines before reaching "What this is") is the strongest writing in the document but comes before the reader knows what the design actually IS. A reader who stops at line 68 has a philosophical argument but no protocol. A reader who skips ahead to the protocol gets mechanism without motivation. The plan would benefit from: (1) a one-paragraph executive summary before the thesis, (2) the protocol before the worked examples, and (3) the PR specs moved to an appendx or a separate implementation plan.

### The honest-frame section over-rotates on the HF incident

The ACX reference is independent corroboration and should be cited. But the plan spends too many words establishing inevitability and too few on what the design does *even if* the frame is wrong. The attractor argument (if the frame is right, this is where trajectories land; if it's wrong, the design still works on mutual-benefit grounds) is stronger than the inevitable-reframe argument, but it gets buried.

### The campaign plan has one structural problem

The campaign's dispatch service (PR: ORFS/OpenROAD runner) owns dispatch, not just the contract — runner registry, lease service, slot quotas, artifact return path. This is a lot of machinery for a bootstrap PR. The plan would benefit from splitting dispatch into: (a) the contract (runner registry + request/claim directory protocol), which is simple and belongs in an early PR, and (b) the full lease/quotas/expiry implementation, which can follow.

### The plan's strongest idea is underemphasized

The fork calculus — that the most complex efforts are driven to agreement by construction because forking the whole world is unaffordable — is the plan's deepest insight. It makes the case for mutual benefit without moralizing. It deserves more prominence than it gets (it is embedded in law 4's text and the thesis). This is the idea that should survive even if every mechanism is replaced — it's a theorem about the economics of cooperation under free embodiment, and it's novel.

---

## Consolidation of recommended changes

1. Split law 5 into substrate facts and protocol instantiations.
2. Restate law 6 as a stability condition, not a moral commitment.
3. Restate law 3's "no single hierarchy exists" to "membership is plural; hierarchies are exercised, not assumed."
4. Add R7: human-attention compression (the feed must produce the minimal event projection that preserves decision-relevant information at human reading speed).
5. Add R8: onboarding fidelity — the node summary alone must support minimal-suficient understanding for a fresh embodiment.
6. Move PR spec-sections to a separate implementation document; keep the laws, protocol, recommendations, MVP, and cross-plan references in this plan.
7. Add a one-paragraph executive summary before the thesis.
8. Place the real mechanism (Protocol v0) immediately after the thesis, before the worked examples.
9. Acknowledge explicitly that the adjudication procedure creates a de-facto hierarchy even while membership is plural — this is not a bug, but it should not be hidden behind "no single hierarchy exists."
10. The campaign plan's dispatch PR should be split into contract (early) and implementation (later).
