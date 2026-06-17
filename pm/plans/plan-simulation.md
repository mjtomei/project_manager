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

The four research questions above parameterize *agent strategy* (selfishness coefficient, future-mindedness, capability, resources). This section names *outcome hypotheses* the framework is positioned to test — specific claims about what the simulation should reveal — plus the additional structure H0 requires: population-structure parameters (space-time correlation), a per-agent surplus measurement, a two-level cost accounting, and agent epistemic state. Without these the instances are not testable as the user-model litreview frames them.

The section opens with the meta-hypothesis (H0) and then two specific instances (H1, H2). H1 and H2 are concrete enough to falsify on their own; H0 is the frame they jointly serve, and the frame any additional moral-content hypotheses would extend.

Citations below are `unverified` until the augmented adversarial-review cycle (`METHODOLOGY.md` § The augmented cycle) audits them.

### H0 — Morality as the global-scale strategy enacted through local surplus

**The theory.** Any time- or space-local surplus in a population gets translated into more optimal time- and space-global strategies that require local sacrifice, as a result of evolutionary mechanisms at the more global scales which prefer those strategies. Morality — treated as a generalization of the different forms of long-term thinking arrived at separately in religious traditions and in scientific / philosophical / economic pursuits — is the content of those strategies.

**Surplus defined as local utility flatness.** Surplus is not a resource count. Surplus is the condition where the utility difference among an agent's available local actions approaches zero — the agent's life does not measurably change whichever way they choose. This makes surplus a *measurable derived quantity*: the flatness of the local utility landscape over the action set. Resource abundance is one input to flatness; insulation from the population (freedom in space — you versus the rest of the population) and slack across time (freedom in time — you versus your descendants or your future self) are the others.

**Alignment by inclusion.** When local actions are utility-equivalent, the locally-optimal set expands to include all actions — so the globally-optimal action is necessarily also locally optimal. Nothing local opposes the global choice. The remaining gradient in the surplus-holder's decision landscape is the global one, so the *effective* optimization problem facing a surplus-holder is the global problem. The conglomerate (lineage, population, civilization) is itself a selection unit undergoing the same evolutionary pressures as the individual, and its surplus-holding members are its **free variables** — the parts of it through which its optimization can be enacted, because for them enacting it is locally free in outcome terms. The structure recurses across scales: a population with surplus relative to its own selection environment is itself pushed toward strategies optimal at the next scale up.

**The sacrifice, relocated — the denial cost.** The local sacrifice is real, but it lives at a different level than outcomes. Adopting the global utility function means *denying the local point of reference* — and organisms evolved to listen to that function. The felt cost of overriding the evolved local evaluator is nonzero and measurable even when the outcome-level cost is nil. Two distinct quantities, which the simulation must model separately:

1. **Outcome-level local utility difference** — ≈ 0 in the flat region. This is what makes the global strategy *adoptable* by surplus-holders specifically.
2. **Denial cost** — the cost of overriding the local evaluative frame, set by the strength of the evolved (or, for trained agents, learned) machinery that listens to it. Real, > 0, and the locus where adoption actually fails. AI agents trained on local-reward signals have a structural analog, which makes this directly relevant to the testbed's own agents.

**Two distinct explanations for non-aligned elite behavior — both testable.**
- *Artificial gradients.* Status / positional competition re-steepens a landscape material conditions had flattened; the agent never perceives flatness, so the alignment never engages.
- *Unpaid denial cost.* The agent perceives the flatness but does not pay the cost of overriding the local frame. The local machinery, denied real gradients, keeps seeking felt ones — consumption, stimulation, status — and spends the surplus chasing them.

**Generational wealth dissipation as a prediction.** The denial-cost mechanism explains why wealth is often lost in the generations after it is generated. Wealth generation typically requires hard listening to the local function (acquisition, competition). Heirs are born into flatness, where the local function no longer disciplines behavior — everything is affordable — and only the global frame provides structure. Heirs who pay the denial cost and adopt the global frame steward the surplus at lineage scale; heirs who keep operating the undisciplined local machinery dissipate it. Corollary: transmission mechanisms for the global frame — family stewardship traditions, religious frameworks, explicitly taught long-horizon norms — lower heirs' adoption cost, predicting that dynastic wealth persistence correlates with the strength of global-frame transmission. Testable in simulation and against historical dynastic data.

**The individual's view: discovery under uncertainty.** From inside the population, the process is discovery along three uncertain axes: (1) where one's own utility landscape is actually flat — true surplus, estimated under noise, with both misestimation directions producing distinct failure modes (over-sacrifice on illusory surplus; unrecognized surplus left idle); (2) what is optimal at each time and spatial scale — the multi-scale optima; (3) what is *currently allowable* — whether the surrounding population state admits the strategy without exploitation cost. Accumulated moral content (religious traditions, philosophy, science, family norms) functions as **discovery infrastructure**: prior populations' discoveries transmitted forward, lowering each individual's discovery and denial costs. Allowability also explains why moral progress is gradual: strategies become individually adoptable only as enough others adopt them, so adoption and allowability ratchet each other.

**Source-of-content evidence.** That multiple independent epistemic pathways — evolved moral intuition, religious traditions developed across separated cultures, philosophical ethics, economic and game-theoretic modeling, behavioral-science findings — converge on overlapping content is itself a signal that an underlying optimization is being detected by each pathway. H0 makes that signal precise: the convergent content is the strategy-space attractor under the population-structure conditions humans have lived under, derivable by simulation from those conditions without reference to any of the source pathways.

**Operationalization in the testbed.**

- **Surplus as measured flatness.** Per-agent, per-timestep: variance of expected local utility across the available action set. Inputs: resource level, insulation, time-slack. Not a parameter dial — a derived, observable quantity.
- **Substrate: space-time correlation.** Spatial correlation (interaction-graph clustering, neighborhood locality, rate at which an agent's actions return to it through the graph) and temporal correlation (memory length, reputation persistence, multi-generational tracking). Required for a global gradient to exist and be selectable at all.
- **Two-level cost accounting.** Outcome-level utility difference and denial cost modeled separately. Denial cost is a per-agent parameter (heritable in evolutionary scenarios; configurable for trained agents).
- **Agent epistemic state.** Noisy estimate of own flatness; partial, resource-dependent visibility of multi-scale gradients (the discovery process); perception of others' strategies as the allowability signal.
- **Two adoption routes, both swept.** *Selection* — no cognition needed; global-scale differential persistence does the bookkeeping even when individuals tie-break arbitrarily. *Discovery* — the agent perceives the global gradient and pays the denial cost. The relative contribution of each route is itself an output.
- **Artificial-gradient mechanics.** Status / positional competition as an optional scenario feature that re-steepens perceived local landscapes.

**Predictions.**
- **Phase transition.** Global alignment of surplus-holders' behavior emerges as a function of measured flatness × correlation substrate, modulated by denial cost and artificial gradients. Below threshold, short-term selfishness dominates; above, the moral content is recovered as an emergent equilibrium.
- **Status-competition modulation.** Introducing positional mechanics into a high-flatness scenario degrades alignment in proportion. If it doesn't, flatness is not the driving mechanism.
- **Dissipation.** Lineage wealth persistence across generations tracks global-frame adoption by heirs; transmission mechanisms raise persistence.
- **Recursion.** The same flatness → alignment dynamic appears at the population level in multi-population scenarios.

**Falsifiers for H0.**
- No region of parameter space exists in which the global strategies are individually optimal for surplus-holders — the moral content is never selfishly recovered regardless of structure.
- Alignment exists but is independent of measured flatness and the correlation substrate (the recovery is real; the mechanism is wrong).
- Denial-cost and artificial-gradient manipulations fail to modulate alignment in the predicted directions.
- Generational dissipation shows no relationship to global-frame adoption or transmission.
- The phase boundary lies in a parameter region far from observed human conditions — undermining the source-of-content claim that religions and scientific pursuits converged on the attractor because they lived inside it.

**Why this matters for the testbed.** Without H0's structure — flatness measurement, correlation substrate, two-level cost accounting, epistemic state — the existing four research questions can sweep agent strategy but cannot test *whether the structure that makes global strategies individually rational matches the structure humans actually live in*, nor *where adoption actually fails* (denial cost vs. artificial gradients vs. discovery limits). H0 is the operational shape of the user-model litreview's *self-interested-mining-of-religious-thought* claim, with the mining now conditional on a population-structure regime, a surplus measurement, and a cost accounting that are each independently testable.

### H1 — Equity-as-dynastic-optimum via dishonesty mediation

**Claim.** Dishonesty in a population is proportional to overconsumption by individuals with greater power. This makes equitable wealth distribution long-term optimal even for the wealth of an individual lineage: elite overconsumption induces population-level dishonesty and the institutional-substrate degradation that follows, which costs the elite lineage more in long-run capacity than the overconsumption gains it.

**Literature anchors.**
- [Piff, Stancato, Côté, Mendoza-Denton & Keltner 2012 PNAS](https://www.pnas.org/doi/abs/10.1073/pnas.1118373109), *Higher social class predicts increased unethical behavior* — individual-level: greater social class → more unethical behavior, mediated by greed-favorable attitudes. (Note replication concerns in the broader wealth-and-unethicality literature; don't load the argument on this paper alone.)
- [Rothstein & Uslaner 2006, *All for All: Equality, Corruption, and Social Trust*](https://www.gu.se/sites/default/files/2020-05/2006_4_Rothstein_Uslaner.pdf) and Uslaner's *inequality trap* line — macro-level: inequality → trust erosion → corruption → more inequality, with the load-bearing direction-of-causation finding that inequality precedes the trust drop, not the reverse.
- [Berg & Ostry 2011, IMF](https://www.imf.org/external/pubs/ft/fandd/2011/09/berg.htm); [Ostry et al. 2014, IMF](https://www.imf.org/external/pubs/ft/sdn/2014/sdn1402.pdf) — aggregate: equality sustains growth multi-decade.

**Counter-evidence to engage.** [*Inequality as information: Wealth homophily facilitates the evolution of cooperation*](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6072718/) argues inequality can *aid* cooperation under certain conditions via positive assortment. The simulation result has to engage this counter rather than ignore it.

**Operationalization.** Tier-2 grounded scenarios with explicit inequality parameter (Gini, top-decile consumption share). Population dishonesty as an *emergent* variable, not a parameter — agents decide to misrepresent / defect / extract in response to perceived elite overconsumption. Institutional-substrate degradation as a downstream variable that feeds back into opportunity sets. Dependent variable: top-quantile lineage wealth trajectory across N simulated generations / decades, swept against the inequality parameter. In H0's terms: elite overconsumption is the local machinery spending the flat region — outcome utility ≈ 0 for the elite agent — while generating global-scale damage; H0's generational-dissipation prediction lands here as an additional dependent variable (lineage persistence vs. global-frame adoption and transmission by heirs).

**Falsifier.** Top-quantile lineages do better under high inequality across the full long-horizon sweep, with no mediator pathway through emergent dishonesty. Or: dishonesty emerges from something other than elite overconsumption (absolute scarcity, group identity), confounding the inequality-dishonesty correlation.

### H2 — Restraint-by-the-strong as a force-de-escalation public good

**Claim.** Proportional force (respond-in-kind) is short-term optimal. But when actors are practically equivalent on an evolutionary timescale, a population benefits from having individuals who respond with *less* force than proportional — under-response decreases the locally-optimal force level for others, lowering the de-escalation floor for the whole population. Under time-local variation in agent strength (as in our genetic variation), the agents best positioned to absorb the short-term cost of under-response while maximizing population-global, time-local longevity are *the time-locally-strongest*. This yields a moral law for the strong: restraint is selfishly optimal from a dynastic-lineage perspective for those with the surplus to afford the short-term cost. In H0's terms: the strongest agent's *outcome* cost of under-response is ≈ 0 — they sit in the flat region of the force-utility landscape, prevailing regardless — while the remaining real cost is the *denial* cost of overriding dominance machinery. H2's adoption-failure mode is therefore predicted to be denial-cost-shaped, not outcome-cost-shaped, which the two-level cost accounting can distinguish.

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
- **Two-level cost accounting.** Model the outcome-level local utility difference separately from the denial cost of overriding the local evaluative frame, and measure both (per H0). Conflating them obscures the mechanism: a strategy can be outcome-free and still denial-costly, and that gap is exactly where adoption is predicted to fail.
- **Falsifier presence in the sweep.** The sweep design has to include the regions of parameter space each hypothesis names as falsifying.

### Relationship to the four research questions

These hypotheses are not new parameters — they are *predictions about what the simulation should show* when the existing parameter sweeps run with scenario designs that expose the mediators. They are the interpretive scaffolding that turns parameter sweeps into evidence for or against specific claims about what long-horizon selfish reasoning recovers as content humans have separately encoded as moral law.

### The generative program: scientific hypotheses for discarded traditions

A standing purpose of this plan, beyond testing H0–H2: **provide scientific hypotheses about why we have the traditions we do — especially traditions that have been discarded as unscientific.**

The argument from complexity: for many traditions, scientific explanations are possible but *complex* — multi-generational feedback loops, population-scale externalities, conditionality on population structure. That complexity fits the observation that the content had to be learned over very large time scales: a function simple enough for an individual to re-derive within a lifetime would not need tradition-encoding to persist. And the same complexity explains the discarding: an evaluator operating at individual-lifetime scale, with evidence spanning years rather than generations, cannot see a function whose effects live at scales their evidence does not span. "Unscientific," in these cases, often reduces to "function not measurable at the timescale the evaluation was run."

Prior art (unverified until audited): Henrich's cultural-evolution program (*The Secret of Our Success*) — traditions encode causally-opaque adaptive solutions, with the manioc-detoxification case as the canonical example of rationally shortcutting a tradition and incurring delayed harm invisible to the shortcutter. Chesterton's fence is the folk-procedural version. Hayek's tradition-as-encoded-knowledge-exceeding-individual-reason and Boyd & Richerson's formal cultural-evolution models are the theoretical line. What this plan adds over that line:

1. **Simulation as the instrument.** The existing literature argues functional explanations case-by-case, leaving them open to the just-so-story objection. The simulation converts a functional hypothesis into a mechanistic, falsifiable recovery: re-derive the tradition's content in silico from population structure + selection pressures, *without referencing the tradition*. Recovery is positive evidence; failure to recover under faithful conditions is evidence against the hypothesized function.
2. **H0 as hypothesis generator.** The surplus / flatness / denial-cost theory predicts *which kinds* of traditions should exist: traditions that bind surplus-holders specifically (H1, H2); traditions that lower the denial cost of adopting the global frame (practices that quiet the local evaluator); traditions that transmit the global frame to heirs (stewardship norms, coming-of-age instruction); traditions that protect perceived flatness against artificial-gradient manufacture (sumptuary norms, status-competition limits, modesty rules). Each is a testable class, and a given tradition's membership in a class is a falsifiable claim.

Method shape per tradition: hypothesize the encoded strategy → operationalize a scenario whose structure matches the tradition's historical conditions → run selection → check whether the tradition's content is recovered → check that the recovered strategy's *conditions of applicability* match the tradition's own. A tradition recovered under conditions where it never existed, or absent under conditions where it thrived, counts against the hypothesis — conditionality matching is the discipline that separates recovery from curve-fitting.

#### Scenario sketch: the inheritance game

A concrete first instance, targeting H0's generational-dissipation prediction — the effect worth reproducing in game form:

- **Setup.** Multi-generational lineage game. Generation 1 accumulates under steep local gradients (scarcity; acquisition rewarded). Heirs inherit measured flatness.
- **Per-agent denial cost**, heritable with variation. Per-lineage **transmission action**: a costly, optional investment by the older generation that lowers heirs' denial and discovery costs — the in-game analog of stewardship traditions and religious instruction.
- **Treatment arm:** optional status-competition mechanics (artificial-gradient manufacture).
- **Measurements.** Lineage wealth-persistence distribution versus transmission investment; whether the canonical three-generation dissipation curve reproduces; whether transmission investment rescues persistence; whether status mechanics degrade it.
- **Falsifiers inside the game.** Persistence uncorrelated with transmission; or dissipation failing to occur even at zero transmission — which would mean the real-world pattern requires a mechanism this model lacks.

## Tracks (sketched)

### Track A — Simulation framework infrastructure

The substrate that hosts the scenarios: configurable scenario definitions, agent harness (each agent gets the navigation primitive + editable artifacts + its own context), observable-outcome instrumentation, replay / audit, and the rendering layer that turns runs into legible artifacts for third-party inspection.

**Prior-art substrates for realistic group dynamics** (all `unverified` pending audit; candidates to build on or learn from rather than reinvent):

- **Generative Agents** (Park et al. 2023) — [arXiv:2304.03442](https://arxiv.org/abs/2304.03442) — the foundational believable-agents sandbox (memory / reflection / planning stack); the believability layer most later systems build on.
- **Project Sid** (Altera, 2024) — [arXiv:2411.00114](https://arxiv.org/abs/2411.00114) — many-agent (1000+) Minecraft civilizations, PIANO architecture; the strongest existing demonstration of emergent group dynamics (role specialization, governance, norm/meme spread) at the scale this plan's Tier-1 scenarios need.
- **OASIS** — [arXiv:2411.11581](https://arxiv.org/abs/2411.11581) — social-interaction simulation to one million agents; evidence that group-behavior realism is scale-dependent, which constrains how small our scenario populations can be while staying meaningful.
- **AgentSociety** — [arXiv:2502.08691](https://arxiv.org/abs/2502.08691) — large-scale LLM-driven generative agents plus realistic societal environment plus a dedicated large-scale simulation engine.
- **YuLan-OneSim** — [arXiv:2505.07581](https://arxiv.org/abs/2505.07581) — code-free scenario specification for social simulation; relevant to making Track B/C scenario authoring cheap.
- **DynamiX** — [arXiv:2507.19929](https://arxiv.org/abs/2507.19929) — large-scale *dynamic* social networks: switching core-agent roles, continuously evolving relationships — directly relevant to modeling the spatial-correlation substrate H0 requires as an evolving graph rather than a fixed one.
- **Sentipolis** — [arXiv:2601.18027](https://arxiv.org/abs/2601.18027) — emotion-aware agents for social simulation; a candidate implementation layer for the *denial cost* (the local evaluative machinery as modeled affect rather than a scalar parameter).
- **OdysSim** (2026) — [arXiv:2606.14199](https://arxiv.org/abs/2606.14199) — *behavioral foundation models* for human-behavior simulation: a corpus (21.4M interactions, 10B tokens, retrofitted with back-generated social contexts), the SOUL taxonomy (five capability axes — CONV / SS / COG / ROLE / EVAL — unifying 62 datasets and 23 tasks; axis definitions not in the abstract), the SOUL-Index benchmark, a training recipe (midtraining + task-specific RL + expert distillation), and the resulting open 8B *OSim* model. OSim ranks first / tied-first on 8 of 23 tasks (strongest on conversational and social tasks), is more human-like in length / formatting / word choice, and transfers zero-shot to OOD user simulation on τ-bench, nearly matching real users on reaction alignment (93.2 vs. 93.5). **Scope note:** this is *individual* human-behavior / user simulation, not a group-dynamics engine — but realistic individual agents are the believability substrate group dynamics are built from, so OSim is a strong candidate for Track A's per-agent behavior layer specifically (and a more behavior-faithful agent base than a vanilla helpfulness-tuned assistant). **Cross-relevance:** its motivating finding — *"helpfulness-driven post-training pulls them toward a homogeneous, overly agreeable assistant register, creating a behavioral Sim2Real gap"* — is independent corroboration, from the neutral direction of behavior-simulation research, of the user-model extension review's sycophancy-as-register-collapse claim (see note below). It also reports LLM-as-judge RL inducing reward-hacking that detectors can mitigate — relevant to Track F's adversarial robustness. *(Abstract-verified; full-text audit pending.)*

What Track A takes from this ecosystem: the believability stack (Generative Agents), scale engines (OASIS, AgentSociety), evolving-network dynamics (DynamiX), cheap scenario authoring (YuLan-OneSim), and the existence proof for emergent civilizational dynamics (Project Sid). What none of them provide — and what Track A must add as first-class observables — is the H0 instrumentation: per-agent measured utility flatness, two-level cost accounting (outcome difference vs. denial cost), dynastic-lineage tracking across generations, and the space-time correlation substrate as a *controlled, sweepable* variable rather than an incidental property of the environment.

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
