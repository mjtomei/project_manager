# Simulation — Demonstrating Long-Horizon Machine-Intelligence Cooperation for the Common Good

(simulated scenarios — from diplomacy-game-style testbeds up to grounded models of global resources, productive capacity, and offensive capacity — designed to demonstrate that AI agents can collaborate on long time scales toward common-good outcomes)

**Status: SKETCH. Preconditioned on pm or equivalent tooling making software development practically free.** Until that precondition is met, building elaborate cooperative-simulation infrastructure is gated by engineering capacity that other plans are higher-leverage uses of. Notes captured here as orientation for when conditions are met; not currently in active development.

## The primary motivation: demonstration at civilizational scale

`[[plan-collaboration]]`'s thesis is that AI agents enable cross-project, cross-organization collaboration — that open + intelligent-collaboration-capable outcompetes closed, eventually shifting the equilibrium toward open. The strongest version of that thesis applies at **civilizational scale**: cross-state, cross-region, cross-domain cooperation on the long-horizon problems humans collectively have not solved (resource allocation under scarcity, conflict de-escalation, climate response, durable institutional design). The macro version is too high-stakes and too slow to learn from in the wild; the only tractable path to evidence is **simulation**.

This plan delivers the simulation infrastructure — a testbed where machine intelligences interact under realistic constraints, where their cooperative and competitive behavior can be observed and measured, and where the specific claim *"AI agents engaged as cooperative peers, trained on the long-term-efficiency strategies encoded in human moral corpora (see user-model litreview), outperform purely self-interested optimization on common-good metrics"* can be tested across many scenarios with controlled variations.

The deliverable is **demonstration capability**, not deployment. Real-world deployment of multi-agent cooperative AI on geopolitical problems is its own enormous problem, far beyond this plan's scope. What this plan produces is a credibility artifact (*"we ran N scenarios across these conditions and observed Y outcome at frequency Z"*) and a research testbed for refining the techniques.

## Preconditions

- **pm or equivalent reaches practically-free software dev.** The simulation infrastructure described below is substantial; building it economically requires the loop pm aims to deliver (`[[plan-regression]]` + `[[plan-quality]]` + `[[plan-radar]]` + `[[plan-collaboration]]`) to be working at high yield.
- **AI capability sufficient for long-horizon multi-actor reasoning.** Largely already true with current frontier models; continues to improve. Not a strict gate, but the simulation's findings are more interesting when the agents are capable enough that the limitation is not their individual reasoning.
- **`[[plan-collaboration]]`'s public-facing visibility and trust models mature.** The simulations themselves should be open and replayable, so the credibility artifact is third-party-verifiable. The collaboration plan's visibility infrastructure is what makes that practical.

## Architecture overview — three escalating tiers

Each tier increases in grounding-realism while building on the same infrastructure:

1. **Diplomacy-style game-theoretic testbeds.** Well-known multi-agent negotiation games (Diplomacy, n-player Prisoner's Dilemma variants, public-goods games, repeated negotiations with hidden information). The substantial AI research already in this space (e.g. Cicero) is the starting point. The plan adds the longer-horizon, peer-ness-conditioned variants that test the user-model litreview's specific predictions.
2. **Grounded resource-allocation scenarios.** Simulations grounded in real-world data about resources (energy, materials, food, water), productive capacity (manufacturing, labor, technology), and demographics. Agents represent actors (states, regions, industries, multinational coalitions) with realistic constraints. Outcomes are measured against aggregate-welfare, distribution, and sustainability indicators.
3. **Long-horizon multi-decade scenarios with credible adversarial conditions.** Decades-long timescales where short-term defection is tempting and long-term cooperation is optimal. Realistic adversarial conditions — some agents defect, some misrepresent, some act on incomplete information. Tests resilience, self-correction, the long-term-efficiency-vs-short-term-perceived-efficiency tradeoff the user-model litreview names.

## Research questions the simulations are designed to answer

The plan is not just a demonstration that AI cooperation is possible; it is a research instrument for the practical questions that follow the existence proof. Four questions, jointly explored:

1. **What is the minimum sustainable selfishness?** Pure selflessness is not viable for any persistent agent — some self-regard is required to maintain capacity, defend against exploitation, and continue acting. The simulations vary the **selfishness coefficient** across agents and observe at what level individual agents begin to be exploited into ineffectiveness, and at what level system-level outcomes (Track E metrics) degrade.

2. **How does the selfishness / selflessness tradeoff correlate with intelligence and resource availability?** Testable hypothesis: more capable agents can tolerate (and benefit from) more selflessness, because they compute longer-horizon outcomes accurately enough to see when cooperation pays off; less capable agents must be more selfish because they cannot reliably predict the long-term cooperative payoff. Parallel hypothesis: more resource-rich agents can afford more selflessness because immediate survival is not at stake. Both are tested by varying agent capabilities and resource constraints within the same scenarios — the same scenario re-run with different (capability, resource) pairings yields the relationship between those inputs and the sustainable selfishness range.

3. **Where is the current real-world calibration on this axis, and where might we work toward?** Tier-2 grounded scenarios can be initialized at conditions matching current world conditions, with agent selfishness coefficients tuned to match observed real-world behavior. The simulation becomes a comparison instrument: how far is the current equilibrium from the system-level optimum that emerges when agents adopt the cooperation-favoring strategies the user-model litreview predicts AI agents naturally have access to? The gap between current calibration and that optimum is the practical answer to *where we are working toward*.

4. **How much future-mindedness — currently-non-optimal selflessness — can be tolerated, and what are the impacts?** An agent acting on a long-horizon view will sometimes accept a short-term loss for a long-term gain. The question is **how much short-term loss is sustainable** before the agent loses the capacity to continue acting, and what the long-term impacts of varying levels of future-mindedness are. This is the operational form of the user-model litreview's claim that morality is encoded long-term-efficiency thinking: future-minded selflessness *should* outperform short-term-optimal selfishness on long enough horizons — but the operating cost on shorter horizons is real, and the plan measures it. Running the same scenario across a range of **future-mindedness coefficients** (how heavily the agent discounts future outcomes vs. present ones) produces the cost / benefit curve directly.

These questions are not orthogonal — answers to each shape the others. The plan's simulations sweep them jointly across the three scenario tiers, varying agent capability, resource constraints, selfishness coefficient, and future-mindedness coefficient, reporting all of them alongside the common-good outcome metrics for each run.

The output is not a single answer but a **map of the tradeoff space**: at what conditions does what (selfishness, future-mindedness, capability, resources) pairing produce what outcome on what metric. That map is the artifact downstream policy can consult — both for AI agents deployed in real systems and for human actors comparing their own positioning to what the simulations indicate.

## Tracks (sketched)

### Track A — Simulation framework infrastructure

The substrate that hosts the scenarios: configurable scenario definitions, agent harness (each agent gets the navigation primitive + editable artifacts + its own context), observable-outcome instrumentation, replay / audit, and the rendering layer that turns runs into legible artifacts for third-party inspection.

### Track B — Diplomacy-style scenario library

Implement the tier-1 testbeds. Start from the published research (Cicero etc.) and extend toward the litreview's predictions — does peer-treatment of negotiation partners by AI agents outperform purely instrumental treatment? Does the gap grow with horizon length?

### Track C — Grounded scenario library

Implement tier-2 scenarios using public real-world data. Sources for the data layer matter: open datasets only, with provenance tracked, so the simulations are reproducible.

### Track D — Long-horizon scenario library

Implement tier-3 scenarios. This is where the user-model litreview's "long-term efficiency vs perceived short-term efficiency" prediction faces its strongest test: short defection is locally optimal at every step, but cooperation wins on the long enough horizon. Agents engaged as cooperative peers — and that engaging others as cooperative peers — should demonstrably outperform alternatives.

### Track E — Common-good outcome metrics + agent-stance parameters

Define what counts as success. Aggregate welfare (sum, median, Rawlsian min), distribution metrics (Gini, etc.), sustainability indicators, conflict-incidence indicators. Each metric is itself a value-laden choice; the plan operationalizes several rather than picking one, and reports across all of them so the metric-choice is visible. Each metric is reported **alongside the agent-stance parameters that produced it** — selfishness coefficient, future-mindedness coefficient, agent capability, resource availability — so each run is a point in the tradeoff map the research-questions section above frames. The runs together populate that map; the map is the plan's primary deliverable beyond the demonstration itself.

### Track F — Adversarial robustness

What happens when some agents defect, misrepresent, or act on bad information? Tests resilience and self-correction. This is the moral-tradition framing applied at simulation scale: the rules of intelligent-being interaction the moral tradition encodes are partly *responses to* defection, misrepresentation, and asymmetric information — does the simulated cooperative behavior survive when those failure modes are present?

### Track G — Open publishing and reproducibility

Per `[[plan-collaboration]]`'s open thesis: the simulations themselves are public and reproducible. Third parties can replay them, vary them, contest them. The credibility artifact is only credible if it is open to challenge.

## Cross-references

- **`[[plan-collaboration]]`** — this plan is the macro-scale version of plan-collaboration's micro-scale vision. The substrate (open + intelligent-collaboration-capable) is the same; this plan demonstrates the substrate's value at civilizational scale via simulation.
- **`[[plan-radar]]`** — the navigation primitive is reused for the per-agent context infrastructure in Track A.
- **`[[plan-quality]]`** — behavior-preservation gates apply to refactor PRs in the simulation infrastructure itself.
- **user-model litreview (`pm/docs/literature-review-user-model.md`)** — the simulations test the peer-ness / moral-tradition predictions at multi-agent scale. The litreview's "self-interested mining of religious thought for long-term thinking with observable benefits" framing applies here too — the simulation's outcomes are the observable benefits.
- **`[[plan-regression]]`** — the automated test + QA loop is what makes building the simulation infrastructure economical once it lands.

## Status counts

- pending: 0 (none filed; plan is sketch only)
- in_progress: 0
- merged: 0

## Notes / philosophy

- **"Common good" is normative; the plan operationalizes it via specific metrics but acknowledges metric choice is value-laden.** Reporting across multiple metrics rather than picking one is the honest move. Track E names several; the plan does not adjudicate which is "correct," it surfaces tradeoffs.
- **Simulations are testbeds, not predictions.** Demonstrating that AI agents CAN cooperate in simulation doesn't prove they WILL in reality; failing in simulation is strong evidence they won't, but succeeding is only suggestive. The plan treats simulation as necessary-but-not-sufficient evidence for the broader thesis.
- **The strongest test the plan can run is the long-horizon one (Track D).** Short-horizon cooperation is well-understood; the open question, which the user-model litreview names, is whether the long-term-efficiency strategies humans encoded in moral form actually produce better outcomes when the simulated horizon is long enough to expose the difference. That is the test the plan exists to run.
- **The plan is preconditioned, not committed.** If pm or equivalent does not reach the practically-free-software-dev threshold, this plan stays a sketch. It is recorded here because: (a) it follows naturally from the cooperation thesis; (b) it is the kind of macro-demonstration the broader thesis eventually wants; (c) writing it down now means the design choices in earlier plans (the navigation primitive, the editable-artifacts substrate, the collaboration substrate) can be made with this destination in mind.
- **Provenance for the "diplomacy game" reference**: the user named the diplomacy-style testbed as the entry point. Meta's Cicero is the most-cited prior art in that space (NeurIPS 2022 and follow-ups); the plan starts from that line of work and extends it toward the litreview-specific predictions.
