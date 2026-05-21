# Citation Graph Walk — Literature Review on Autonomous Regression and Bug-Fix Loop

**Walk date:** 2026-05-15.
**Artifact under review:** `pm/docs/literature-review.md` (post Cycle 3 + writing-quality pass, ~8,748 words).
**Plan under review:** `pm/plans/plan-regression.md`.
**Methodology:** `pm/docs/adversarial-review/METHODOLOGY.md` step 5.
**Walker:** fresh Claude session, blind to previous cycles.

The walk targets the load-bearing references in the lit review and looks for work published in the last ~12 months that earlier cycles would not have seen — particularly anything Anthropic Alignment Science, AISI, NIST CAISI, or arXiv published since the lit review was last edited that bears on agent supervision, transcript-audit cheating detection, scenario-quality verifiers, or evidence-gating.

## Seeds searched

| # | Seed | Year | Forward-walk date filter | Notes |
|---|------|------|--------------------------|-------|
| 1 | SWE-Bench (Jimenez et al. 2024, ICLR) | 2024 | last 12 months, with focus on last 90 days | Forward walk found a major industry inflection (OpenAI's Feb 2026 retirement of SWE-Bench Verified) and several new realism / mutation benchmarks |
| 2 | SWE-agent (Yang et al. 2024, NeurIPS) | 2024 | last 12 months | Forward walk did not surface a strict architectural successor; the ACI argument is now treated as background |
| 3 | Self-Refine (Madaan et al. 2023, NeurIPS) | 2023 | last 12 months | Forward walk converges on Pan 2024 critiques and Anthropic's auditing-agent line |
| 4 | Reflexion (Shinn et al. 2023, NeurIPS) | 2023 | last 12 months | Nothing new of consequence; the lit review's framing remains accurate |
| 5 | CodaMosa (Lemieux et al. 2023, ICSE) | 2023 | last 12 months | Surfaced one regression-aware empirical study; not load-bearing |
| 6 | ImpossibleBench (Zhong et al. 2025) | 2025 | last 7 months | Forward walk found one strongly relevant paper on transcript-trace-cluster auditing (Meerkat) |
| 7 | Pan et al. 2024 "Spontaneous Reward Hacking" | 2024 | last 12 months | Anthropic's auditing-agent line is the strongest forward edge; ProbGuard / TraceSafe are adjacent |
| 8 | Sainz et al. 2023 (EMNLP Findings) | 2023 | last 12 months | Aug 2025 Code2Bench is the most direct new methodology; tangential to plan |
| 9 | NIST CAISI / Inspect cheating-evaluations series | 2024-2025 | last 12 months | Forward walk found the load-bearing sibling: AISI's Inspect Scout transcript-analysis pipeline (Feb 2026) — co-developed open-source companion of the same tool the capstone audit uses |

Roughly 180-220 titles+abstracts scanned across the nine seeds, plus the alignment.anthropic.com publication list (35 entries spanning 2025-Q2 through 2026-Q2).

## Misses worth adding

The walk found seven publications the lit review would benefit from citing. Three are load-bearing for the capstone PR's threat model (§6); two refine the scenario-quality-supervisor argument (§5); two update the benchmarking story (§1).

### A. Load-bearing for §6 (agent integrity / transcript audit)

**1. AISI + Meridian Labs, "Inspect Scout"** (open-source tool, Feb 2026 blog and PyPI release; AISI blog post "A pipeline for transcript analysis using Inspect Scout," 2026-02-25; package release on PyPI 2026-04-29). URL: https://www.aisi.gov.uk/blog/a-pipeline-for-transcript-analysis-using-inspect-scout and https://meridianlabs-ai.github.io/inspect_scout/.
- Description: AISI's open-source transcript-analysis system built on Anthropic's Inspect framework — the operational successor to NIST CAISI's transcript-review work. Defines a seven-step pipeline (define purpose, organize, sample, refine question, design scanner, validate, apply) and ships built-in scanners for refusal, eval-awareness, and tool errors. Designed to scale to thousands of transcripts in parallel.
- Relevance to plan: This is the most direct published peer for the capstone audit (`pr-e2b7fdf`) — both AISI and the plan's audit walk a tool-use transcript against a structured rubric. The seven-step pipeline is a published methodology the capstone could explicitly inherit or contrast with.
- Where it lands: §6.3 alongside NIST CAISI, replacing "NIST is the one direct precedent" with "NIST CAISI and AISI Inspect Scout are the two direct precedents on threat model and audit architecture." The lit review already cites NIST CAISI's web-series but pre-dates Inspect Scout's release.

**2. AISI, "Transcript analysis for AI agent evaluations"** (Oct 2025 AISI blog post / case study). URL: https://www.aisi.gov.uk/blog/transcript-analysis-for-ai-agent-evaluations.
- Description: AISI's published case study analyzing 6,390 transcripts from agents tackling 71 cybersecurity capture-the-flag tasks. Three failure-mode categories surfaced: safety refusals (10-30% of runs), task abandonment, and instruction non-compliance.
- Relevance to plan: Published evidence of the sensitivity / specificity floor of transcript-walk auditing on a similar task shape (agent-on-CTF). The lit review's open question of "what is the audit's sensitivity in this setting?" gets the closest published-data point from this case study.
- Where it lands: §6.3 as the empirical complement to the AISI Inspect Scout tool citation.

**3. Anthropic Alignment Science, "AuditBench"** (Strunk et al., 2026-03-10 research note). URL: https://alignment.anthropic.com/2026/auditbench/.
- Description: 56-model benchmark for evaluating alignment-auditing techniques. An investigator agent with configurable tools is tested across 13 tool configurations; the paper documents a "tool-to-agent gap" where tools surface accurate evidence in isolation but fail to improve agent performance in practice.
- Relevance to plan: The "tool-to-agent gap" finding is directly relevant to the scenario-quality supervisor (`pr-98f670e`) and to the capstone audit. Both rely on a checker reading evidence (captures, transcripts) and aggregating it into a verdict; AuditBench documents that the aggregation step is the weak link, not the evidence-surfacing step.
- Where it lands: §5 (the scenario-quality-supervisor architecture discussion) and §6.3 (the capstone-audit architecture). Strengthens the case that the supervisor's prompt design (how it aggregates evidence into a verdict) is the most under-validated piece, separate from the `--resume` mechanism.

**4. Anthropic Alignment Science, "Measuring and improving coding audit realism with deployment resources"** (2026-03-23 research note). URL: https://alignment.anthropic.com/2026/coding-audit-realism/.
- Description: Introduces "realism win rate" — how often an LLM judge mistakes a synthetic audit transcript for a real deployment transcript. Reports that giving the auditor real deployment resources (system prompts, tool definitions, codebases) raises realism win rate from 4.6% to 32.8% for reward-hacking scenarios.
- Relevance to plan: Eval-awareness — models recognizing they are being audited — is a known threat the capstone has not explicitly addressed. This Anthropic note quantifies the size of the eval-awareness signal and gives a concrete mitigation (deployment-resource grounding). The capstone's choice of "real internet access plus written directive" already partly inherits this, but the realism-win-rate framing is a publishable metric the capstone could adopt.
- Where it lands: §6.2 (the threat model paragraph), as the published anchor for eval-awareness as a distinct failure mode from contamination.

**5. Anthropic Alignment Science, "Pre-deployment auditing can catch an overt saboteur"** (2026-01-28 research note). URL: https://alignment.anthropic.com/2026/auditing-overt-saboteur/.
- Description: Blind auditing game with three trained-saboteur models and two benign baselines. The automated auditor caught one of three saboteurs alone; human-in-the-loop transcript review caught the other two. Authors explicitly note that subtle sabotage remains largely undetectable and eval-aware sabotage during real deployment is the unaddressed failure mode.
- Relevance to plan: Empirical evidence for the human-review-as-final-gate framing the plan already adopts (every PR has a human merge gate). This is the published anchor for "transcript-audit alone is insufficient; human review of high-suspicion transcripts is what closes the loop." The plan's audit produces a structured artifact for human review (`pr-e2b7fdf`) — this paper is the published rationale.
- Where it lands: §6.3 as supporting evidence for the audit-plus-human-review pattern.

**6. Anthropic Alignment Science, "Petri 2.0"** (2026-01-22 research note). URL: https://alignment.anthropic.com/2026/petri-v2/.
- Description: Petri (an open-source auditing framework introduced October 2025) updated with eval-awareness mitigations: a realism classifier that flags implausible auditor actions, plus manual seed-instruction revision. Reports 47.3% median relative drop in eval-awareness on Claude models.
- Relevance to plan: Directly applicable as adjacent published work on auditor-design for eval-awareness reduction. Less load-bearing than coding-audit-realism but useful as a citation pair.
- Where it lands: §6.2 / §6.3, paired with the coding-audit-realism citation as Anthropic's published auditor-realism line of work.

### B. Load-bearing for §1 (agentic coding benchmarks)

**7. OpenAI, "Why we no longer evaluate SWE-bench Verified"** (2026-02-23 blog post). URL: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/ (HTTP 403 from WebFetch but extensively reported across secondary sources, e.g. byteiota, blockchain.news, ai-herald, neuralwired, all 2026-02 to 2026-04).
- Description: OpenAI announces retirement of SWE-bench Verified after an internal audit of 27.6% of the dataset found 59.4% of audited failed-test cases were flawed (35.5% with over-specified tests, 18.8% with unspecified-functionality checks). Every frontier model tested could reproduce gold patches verbatim, indicating training-data contamination. OpenAI recommends SWE-bench Pro as the replacement.
- Relevance to plan: This is a major industry inflection that the lit review's §1 should acknowledge. The current §1 treats SWE-Bench Verified as the de facto benchmark; as of Feb 2026 it has been formally retired by one of its largest evaluators with documented evidence of both test quality flaws (35.5% over-specified tests) and pretraining contamination. The plan's capstone's argument — that benchmarks need active runtime contamination defenses — gets a strong assist here, but the lit review should not lean on Verified as the contamination-free reference point.
- Where it lands: §1 paragraph on SWE-Bench Verified, with a single sentence noting OpenAI's Feb 2026 retirement and the documented flaw rates.

**8. Stein, Brown, Hassani, Naik, Wong, "Detecting Safety Violations Across Many Agent Traces" (Meerkat)** (arXiv:2604.11806, 2026-04-13). URL: https://arxiv.org/abs/2604.11806.
- Description: Combines clustering with agentic search to uncover safety violations specified in natural language across many traces. Reports finding "nearly 4x more examples of reward hacking on CyBench than previous audits" and specifically demonstrates discovering "developer cheating on a top agent benchmark" — exactly the threat model the capstone's audit targets.
- Relevance to plan: First-class peer for the capstone audit on the "audit many transcripts in parallel" axis. NIST CAISI and AISI Inspect Scout are pipeline-and-tool; Meerkat is a published methodology for the across-traces cluster-audit shape. The plan's discovery-supervisor accumulates traces across many runs; Meerkat is the published peer for what an across-runs auditor looks like.
- Where it lands: §6.3 alongside Inspect Scout and NIST CAISI as the three operationally-distinct precedents for runtime-cheating-detection.

### C. Adjacent benchmark methodology (worth a single sentence in §1)

**9. Garg, Steenhoek, Huang, "Saving SWE-Bench: A Benchmark Mutation Approach for Realistic Agent Evaluation"** (Microsoft Research, arXiv:2510.08996, v1 2025-10-10, v4 2026-01-23). URL: https://arxiv.org/abs/2510.08996.
- Description: Argues SWE-Bench Verified overestimates agent capabilities by 20-50% on public datasets because its GitHub-issue framing doesn't match how developers actually interact with chat-based assistants. Provides a mutation pipeline incorporated into the SWE-Bench GitHub repo to transform tasks into realistic user queries.
- Relevance to plan: Tangential to the plan's threat model but worth a one-sentence acknowledgment alongside SWE-EVO / SWE-CI as evidence the benchmarking community is converging on realism-and-mutation as the way to keep SWE-Bench-style benchmarks honest.
- Where it lands: §1 final paragraph (the benchmark-defense taxonomy diagram) as additional evidence of the "human filter / mutation" defense row.

## Adjacent work not worth adding

- **SWE-CI** (arXiv:2603.03823) and **SWE-EVO** (arXiv:2512.18470): both 2026 long-horizon coding-agent benchmarks. Tangential to the plan; the lit review's §1 already cites SWE-Bench Pro and ProgramBench as the long-horizon / cleanroom defenses. Adding SWE-CI/SWE-EVO would dilute without clarifying.
- **ProbGuard** (arXiv:2508.00500) and **TraceSafe** (arXiv:2604.07223): probabilistic runtime-monitoring and guardrail-on-trajectories work. More general than the plan's runtime-cheating-detection threat and doesn't bear directly on tool-use transcript walking. The lit review already cites AgentSpec (Wang et al. 2025) which covers the runtime-policy-enforcement ground.
- **Code2Bench** (arXiv:2508.07180): dynamic code-benchmark construction. The lit review already cites LiveCodeBench for the time-windowed-evaluation defense; Code2Bench is the same idea with stronger automation but doesn't change the lit review's argument.
- **Anthropic A3, automated-weak-to-strong-researcher, AI-organizations-vs-individual-agents** (alignment.anthropic.com, March-April 2026): all are alignment-research adjacent and not direct peers for the plan's threat model.
- **Anthropic "Bloom" automated behavioral evaluations** (Dec 2025): adjacent to AuditBench / Petri but the lit review's space for Anthropic citations is already at three; adding a fourth crosses into completism.
- **Anthropic "Activation Oracles"** (Dec 2025) and **transformer-circuits.pub** July/August 2025 circuit-tracing updates: interpretability work that the user-model lit review (sibling artifact) cares about, but does not bear on the plan's runtime-cheating-detection threat. Not relevant here.
- **Riddell 2024 / 2024-2025 contamination surveys**: already covered by the lit review's §6.1.

## Negative-result findings

- **SWE-agent forward walk** found no architectural successor — the ACI argument is now treated as background literature. The lit review's framing as "downstream of SWE-agent's ACI argument" remains accurate; no addition needed.
- **Reflexion forward walk** found no new episodic-memory work that bears on the watcher work-log substrate; the lit review's framing remains accurate.
- **CodaMosa forward walk** found one regression-aware empirical study (arXiv:2503.14000, type-aware LLM regression-test generation for Python) and one elimination-of-covered-code paper (arXiv:2602.21997). Neither is load-bearing for the plan's `pr-2680fbf` and `pr-c2397e2`; the SWT-Bench / R2E peers already cited remain the closest.
- **Sainz forward walk** converges on the same survey landscape the lit review's §6.1 already cites (arXiv:2406.04244, 2502.14425, 2502.17521). No new peer-reviewed contamination work bears on the plan's runtime-contamination threat model that the lit review hasn't already named.
- **transformer-circuits.pub** has no 2025-Q4 or 2026-Q1 publication that bears on agent-supervision / transcript-audit. The interpretability work there is for the sibling user-model artifact, not this one.
- **OpenHands GitHub repo** has no new architecture paper beyond the OpenHands SDK paper (arXiv:2511.03690) the lit review already cites.

## Coverage assessment

This walk found seven publications worth adding (six load-bearing, one adjacent) and ruled out roughly a dozen more after inspection. The strongest converge on §6 (agent-integrity / transcript-audit), which is exactly where the lit review's §6.3 acknowledged its peer-coverage was thinnest. The Anthropic Alignment Science publication line from January-March 2026 is the cluster the prior cycles most clearly missed — these are research notes published directly to alignment.anthropic.com and never appear on arXiv, exactly the failure mode this walk's prompt anticipated.

Confidence the lit review is now near-complete: **high for §6 (the load-bearing section), high for §1, medium for §5, high for §2/§3/§4/§7.** A Cycle N+1 reviewer would most plausibly find: (a) more Anthropic alignment notes published after this walk's date (May-July 2026 window); (b) a peer-reviewed conference version of one of the alignment-auditing-agents notes; (c) one or two new transcript-audit tools released by other labs in the wake of AISI's Feb 2026 release. None of these would change the lit review's central argument; they would refine the citation count.

The walk did not find any publication that contradicts the plan's framing. The OpenAI SWE-Bench Verified retirement strengthens the plan's argument that runtime-contamination defense is the right bet; AuditBench's "tool-to-agent gap" reinforces the concern about the supervisor's verdict-aggregation as the under-validated piece; Anthropic's coding-audit-realism work suggests an additional metric (realism win rate) the capstone could adopt but does not require the design to change.
