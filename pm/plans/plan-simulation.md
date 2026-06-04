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

## Candidate hypotheses: long-horizon selfish strategies for the strong

The four research questions above parameterize *agent strategy* (selfishness coefficient, future-mindedness, capability, resources). This section names *outcome hypotheses* the framework is positioned to test — specific claims about what the simulation should reveal when those parameter sweeps run, plus one additional population-structure dimension (H0) without which the others are not testable as the user-model litreview frames them.

The section opens with a meta-hypothesis (H0) and then two specific instances (H1, H2). H1 and H2 are concrete enough to falsify on their own; H0 is the broader frame they jointly serve, and the frame any additional moral-content hypotheses would also extend.

Citations below are `unverified` until the augmented adversarial-review cycle (`METHODOLOGY.md` § The augmented cycle) audits them.

### H0 — Morality as long-horizon strategy operationalized by space-time correlation under sufficient intelligence

**Claim.** Morality, treated as a generalization of the different forms of long-term thinking arrived at separately in religious traditions and in scientific / philosophical / economic pursuits, is the **operationalization** of long-horizon selfish reasoning in populations whose interactions exhibit sufficient **space-time correlation** — actions propagate back to the actor through spatial structure and temporal persistence — and whose actors have sufficient **intelligence** to perceive those propagations. Under those conditions, the strategies humans have separately encoded as moral content become *locally* optimal (individually, not only population-level optimal), which is what makes them adopted rather than merely admired. Below the correlation threshold or the intelligence threshold, short-term selfishness wins and the moral strategies are dominated.

H1 and H2 below are *specific instances* — concrete moral-content predictions that H0 expects to hold above the threshold and fail below it.

**Source-of-content evidence.** That multiple independent epistemic pathways — evolved moral intuition, religious traditions developed across separated cultures, philosophical ethics, economic and game-theoretic modeling, behavioral-science findings — converge on overlapping content on the questions H1 and H2 name is itself a signal that an underlying optimization is being detected by each pathway. H0 makes that signal precise: the convergent content is the strategy-space attractor under the space-time-correlation-and-intelligence conditions humans have lived under, derivable by simulation from those conditions without reference to any of the source pathways.

**Operationalization in the testbed.** H0 requires extending the existing parameter sweep with population-structure parameters that the four research questions above do not currently name:

- **Spatial correlation.** The interaction-graph's clustering coefficient, neighborhood locality, the rate at which an agent's actions return to it through the spatial structure (graph-distance × diffusion-rate of consequence). Operationalized as a sweepable structural parameter on the agent network.
- **Temporal correlation.** Memory length, reputation persistence, the degree to which past actions remain observable and consequential in future interactions. Multi-generational tracking persists actions across the dynastic-lineage timescale H1 and H2 require.
- **Intelligence.** Already parameterized as the capability axis of research question 2, but H0 makes the joint dependence explicit — intelligence is necessary but not sufficient; intelligence at low correlation does nothing.

The H0 sweep is (spatial correlation × temporal correlation × intelligence) → measure the fraction of long-horizon / moral-content strategies that are individually optimal. The prediction is a **phase transition** in strategy space: below threshold along any of the three axes, short-term selfishness dominates; above threshold along all three, long-horizon strategies become individually optimal and the moral content is recovered as an emergent equilibrium.

**Falsifiers for H0.**
- No region of (spatial × temporal × intelligence) parameter space exists in which long-horizon strategies are individually optimal — i.e., the moral strategies are *never* selfishly recovered regardless of population structure or cognition.
- The alignment exists but is independent of the named parameters (so the recovery is real but the population-structure-and-intelligence mechanism is wrong).
- The phase transition exists but in a region of parameter space so different from observed human conditions that the source-of-content claim — that religions and scientific pursuits converged on it because they were detecting the same optimization — does not hold. (The simulation's threshold being far from human-condition values would be a strong negative result.)

**Why this matters for the testbed.** Without H0's population-structure parameters, the existing four research questions can sweep agent strategy but cannot test *whether the structure that makes long-horizon strategies individually rational matches the structure humans actually live in*. H0 is the operational shape of the user-model litreview's *self-interested-mining-of-religious-thought* claim, with the added precision that the mining is conditional on a population-structure regime that is itself a testable variable.

### H1 — Equity-as-dynastic-optimum via dishonesty mediation

**Claim.** Dishonesty in a population is proportional to overconsumption by individuals with greater power. This makes equitable wealth distribution long-term optimal even for the wealth of an individual lineage: elite overconsumption induces population-level dishonesty and the institutional-substrate degradation that follows, which costs the elite lineage more in long-run capacity than the overconsumption gains it.

**Literature anchors.**
- [Piff, Stancato, Côté, Mendoza-Denton & Keltner 2012 PNAS](https://www.pnas.org/doi/abs/10.1073/pnas.1118373109), *Higher social class predicts increased unethical behavior* — individual-level: greater social class → more unethical behavior, mediated by greed-favorable attitudes. (Note replication concerns in the broader wealth-and-unethicality literature; don't load the argument on this paper alone.)
- [Rothstein & Uslaner 2006, *All for All: Equality, Corruption, and Social Trust*](https://www.gu.se/sites/default/files/2020-05/2006_4_Rothstein_Uslaner.pdf) and Uslaner's *inequality trap* line — macro-level: inequality → trust erosion → corruption → more inequality, with the load-bearing direction-of-causation finding that inequality precedes the trust drop, not the reverse.
- [Berg & Ostry 2011, IMF](https://www.imf.org/external/pubs/ft/fandd/2011/09/berg.htm); [Ostry et al. 2014, IMF](https://www.imf.org/external/pubs/ft/sdn/2014/sdn1402.pdf) — aggregate: equality sustains growth multi-decade.

**Counter-evidence to engage.** [*Inequality as information: Wealth homophily facilitates the evolution of cooperation*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6072718/) argues inequality can *aid* cooperation under certain conditions via positive assortment. The simulation result has to engage this counter rather than ignore it.

**Operationalization.** Tier-2 grounded scenarios with explicit inequality parameter (Gini, top-decile consumption share). Population dishonesty as an *emergent* variable, not a parameter — agents decide to misrepresent / defect / extract in response to perceived elite overconsumption. Institutional-substrate degradation as a downstream variable that feeds back into opportunity sets. Dependent variable: top-quantile lineage wealth trajectory across N simulated generations / decades, swept against the inequality parameter.

**Falsifier.** Top-quantile lineages do better under high inequality across the full long-horizon sweep, with no mediator pathway through emergent dishonesty. Or: dishonesty emerges from something other than elite overconsumption (absolute scarcity, group identity), confounding the inequality-dishonesty correlation.

### H2 — Restraint-by-the-strong as a force-de-escalation public good

**Claim.** Proportional force (respond-in-kind) is short-term optimal. But when actors are practically equivalent on an evolutionary timescale, a population benefits from having individuals who respond with *less* force than proportional — under-response decreases the locally-optimal force level for others, lowering the de-escalation floor for the whole population. Under time-local variation in agent strength (as in our genetic variation), the agents best positioned to absorb the short-term cost of under-response while maximizing population-global, time-local longevity are *the time-locally-strongest*. This yields a moral law for the strong: restraint is selfishly optimal from a dynastic-lineage perspective for those with the surplus to afford the short-term cost.

**Literature anchors.**
- Axelrod 1984, *The Evolution of Cooperation* — iterated-game tournaments establishing tit-for-tat's effectiveness; the parametric baseline against which under-proportional strategies must be measured.
- Nowak & Sigmund — *generous tit-for-tat* and *win-stay-lose-shift*; forgiveness-based strategies outperform strict TFT under noise, giving the under-proportional-response intuition direct game-theoretic precedent.
- Bowles & Gintis, *A Cooperative Species* — group-selection arguments for prosocial strategies.
- Wrangham, *The Goodness Paradox* / self-domestication hypothesis — human evolution may have selected against reactive aggression in ways that compound with H2's logic.
- Boehm, *Hierarchy in the Forest* — reverse-dominance hierarchies (the strong restrained by collective sanction); H2 asks the parallel question of whether selfish-rational reasoning leads the strong to restrain *themselves* without coercion.
- Zahavi's handicap principle / costly-signaling theory — restraint as a costly signal only the strong can afford.

**Counter-evidence to engage.** Hawk-Dove with strength asymmetry classically predicts the strongest play hawk against weaker opponents; H2 requires reasoning at a higher level of abstraction (population-level de-escalation floor as the locus of fitness). Multi-level / group-selection skepticism (Williams, Pinker) is part of the engagement burden.

**Operationalization.** Tier-1 / Tier-2 iterated-conflict scenarios with explicit *strength heterogeneity* across agents (a per-agent strength parameter, time-locally varying — i.e., resembling intra-population genetic variation). Add a *force-response coefficient* per agent (proportional / less-than-proportional / more-than-proportional). Track the population's *optimal-force level* — the strategy a fresh entrant should adopt — as an emergent function of the existing response distribution. Sweep: force-response coefficient × strength quantile × time horizon. The H2 prediction is that lineages of the time-locally-strongest do best with *less-than-proportional* force response over long horizons, with the de-escalation-floor reduction as the mediator.

**Dependent variables.** Population-global longevity (time until collapse or sub-threshold stabilization); lineage wealth / fitness of the top-strength quantile across long horizons; de-escalation floor (lowest force level that still survives).

**Falsifier.** Lineages of the time-locally-strongest do best with proportional or super-proportional response across the full sweep, at no horizon does under-response win. Or: the de-escalation-floor reduction does occur but the lineage payoff is captured by less-strong free-riders, breaking the dynastic-self-interest argument.

### Shared structural commitments for testing H1 and H2

- **Long-horizon evaluation.** The dynastic-lineage payoff comparison only makes sense at horizons long enough for the population-level externality to feed back. Tier-3 long-horizon scenarios are where these are testable.
- **Top-quantile measurement.** The load-bearing comparison is the top-quantile lineage trajectory, not the population mean. Reporting only the mean would miss the claim.
- **Mediator-explicit modeling.** The simulation has to expose the *mechanism* — population dishonesty for H1, de-escalation floor for H2 — as an emergent variable that can be observed and intervened on. Sweeps that only correlate the parameter to the outcome without observing the mediator don't test the claim.
- **Falsifier presence in the sweep.** The sweep design has to include the regions of parameter space each hypothesis names as falsifying.

### Relationship to the four research questions

These hypotheses are not new parameters — they are *predictions about what the simulation should show* when the existing parameter sweeps run with scenario designs that expose the mediators. They are the interpretive scaffolding that turns parameter sweeps into evidence for or against specific claims about what long-horizon selfish reasoning recovers as content humans have separately encoded as moral law.

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
