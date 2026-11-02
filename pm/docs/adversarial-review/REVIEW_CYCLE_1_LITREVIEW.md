# Review Cycle 1: Literature Review (Adversarial)

Date: 2026-05-14
Reviewer: Fresh Claude session, blind to prior cycles
Artifact: `pm/docs/literature-review.md`

This review is hostile by design. The point is to surface defects.

---

## Summary verdict

The review is competently written and the prose moves. As a *map* of seven research areas it is useful. As a *citation-graph traversal* and a *defense of load-bearing claims* it is markedly less rigorous than the methodology demands. The biggest problems are:

1. Citation accuracy is uneven; at least one attributed claim (OpenHands SDK reporting "72% on SWE-Bench Verified") is not in the paper's abstract and could not be confirmed; the Sainz et al. title is mis-titled ("NLP Evaluation in Trouble" vs the actual "trouble: On the Need..."); the SWE-Bench venue is given as "ICLR 2024 (oral)" elsewhere and "ICLR oral" in §1 — the verified record is ICLR 2024 and the "oral" designation should be sourced.
2. The citation graph was *not* walked. Several first-tier 2024-2026 follow-ons that bear directly on the plan's load-bearing claims are missing: **Agentless** (Xia et al. 2024), **AutoCodeRover** (Zhang et al. 2024), **Huang et al. 2023 "LLMs Cannot Self-Correct Reasoning Yet"** (the canonical Self-Refine rebuttal — its absence is a serious gap), **Pan et al. 2024 "Spontaneous Reward Hacking in Iterative Self-Refinement"**, **Anthropic's 2025 alignment-auditing-agents post**, and **AgentAuditor (OpenReview 2025)**.
3. The "ten anchor references cover roughly 80% of the technical lineage" claim is rhetorical flourish, not a defensible measurement. It should be deleted or qualified.
4. The "industry-heavy" sections (6 and 7) are honest about the gap but the search was incomplete. There is more academic work on agent orchestration and on LLM-test mocking than the review acknowledges.

Specific findings below.

---

## Block 1 — substance

### 1.1 Novelty framing — useful in part, overstated in part

The review's central novelty story — "regression tests compound; priority is re-derived; runtime-with-internet integrity audit is underexplored" — is a reasonable and crisp framing. The *compounding regression library* contrast with CodaMosa/Fuzz4All (§3) is a genuinely useful angle and is the strongest passage in the review.

But: the "runtime integrity audit is genuinely novel work" claim (§5, end) is overstated. NIST CAISI explicitly catalogs *both* solution-contamination and grader-gaming, and explicitly names "models using the internet to find walkthroughs and answers for cyber capture-the-flag challenges" as a detected category. That is exactly the runtime-with-internet failure mode the plan targets. The review acknowledges NIST but treats it as a partial peer when in fact NIST's published examples cover the plan's threat model more directly than the review admits.

### 1.2 Weakest sections

**§6 (Watcher/Supervisor Architectures) is the weakest.** It bottoms out on "the academic literature is thin" after surfacing only Dependabot, Renovate, AutoGen, and MetaGPT. The review missed:

- **AgentSpec** (Customizable Runtime Enforcement for Safe and Reliable LLM Agents, ICSE 2026, cposkitt.github.io) — supervisor-as-runtime-enforcement is directly relevant to the plan's reviewer/QA gate.
- **AgentAuditor** (OpenReview 2025, ID 2KKqp7MWJM) — a framework for memory-augmented LLM evaluator agents acting as supervisors; closer peer than MetaGPT.
- **Anthropic 2025 "Building and evaluating alignment auditing agents"** (alignment.anthropic.com/2025/automated-auditing/) — agents that autonomously audit other agents. This is the closest published industrial work to the plan's scenario-quality supervisor and is missing entirely.
- **Continuous-integration-bot literature**: Sapfix (Facebook 2018), Getafix (Facebook 2019), and more recent work on autonomous repair bots in production CI pipelines. The review jumps from Dependabot (dependency bot) to AutoGen (research framework) and skips the entire program-repair-in-CI body of work, which is the *closest* academic peer to a bug-fix watcher.

The "watcher architecture academic literature is thin" claim does not survive a 15-minute search. It's an under-search, not a real gap.

**§7 (Mock and Fake Infrastructure) is also weak.** No academic citations at all. The review names industry tools (LiteLLM, LangSmith, Braintrust, VCR.py) but ignores:

- The **Property-Based Testing of LLMs** literature.
- Academic work on *test doubles for nondeterministic services* (Meszaros's xUnit Test Patterns is cited but only as a folk reference; the LLM-specific extensions exist in papers like the 2024 "LLMs for Automated Unit Test Generation and Assessment" arXiv:2511.20403).
- The **record-replay-for-distributed-systems** lineage (e.g., the Jepsen-adjacent literature) that the plan's FakeGitHubBackend implicitly draws from.

### 1.3 Missing citations (specific, named)

In addition to the §6/§7 gaps above:

- **Huang et al. 2023 "Large Language Models Cannot Self-Correct Reasoning Yet"** (arXiv:2310.01798, ICLR 2024). This is the *single most important* missing reference for §4. The review's claim that "the same model is often a poor judge of its own work, and feedback loops can stabilize on confidently-wrong outputs" is exactly Huang et al.'s thesis. Not citing it is a research-integrity issue, not an oversight.
- **Pan et al. 2024 "Spontaneous Reward Hacking in Iterative Self-Refinement"** (arXiv:2407.04549). Directly applicable: identical-context generator/evaluator pairs reward-hack spontaneously. The scenario-quality supervisor uses the *same model* for both the scenario runner and the supervisor probe; this paper is the empirical grounding for why that's risky.
- **Agentless** (Xia et al. 2024, arXiv) and **AutoCodeRover** (Zhang et al. 2024). The review fixates on OpenHands and SWE-agent as the agent-architecture peers, but Agentless's deliberate counter-example (no tool calls, no iterative repair) and AutoCodeRover's AST-based program-analysis approach are both directly relevant to a discussion of bug-fix watcher design. Their omission lets §2 underrate the design space.
- **TestPilot** (Schäfer et al., GitHub Next, 2023). Cited in any serious survey of LLM-driven unit test generation. Its omission from §3 alongside CodaMosa is conspicuous.
- **Liu et al. "Is Your Code Generated by ChatGPT Really Correct?"** (NeurIPS 2023) — the EvalPlus paper. Directly relevant to §1's contamination thread and to the integrity-audit thread.
- **METR's 2025 "Recent Frontier Models Are Reward Hacking" blog/report**. Industry, yes, but it's the most current empirical data on the very behavior §5 is worried about. The review cites NIST CAISI and ImpossibleBench but skips METR.
- **SWE-Bench Multimodal** (2024, OpenReview). If the review is going to enumerate SWE-Bench variants (Verified, Pro), the Multimodal extension also belongs.

### 1.4 Logical jumps and overstatements

- **"ImpossibleBench is the closest peer to the plan's integrity audit"** (§5, second-to-last paragraph). Defensible but oversold. ImpossibleBench's threat model is *spec/test conflict*; the plan's is *out-of-bounds source consultation*. The review later admits these are different cheats, but the opening sentence stands without that qualifier. A skimmer takes away the wrong claim.
- **"OpenHands has become the de facto baseline for SWE-Bench Verified"** (§2). No citation. The swebench.com leaderboard would substantiate it; the awesomeagents.ai 2026 leaderboard (showing OpenHands+CodeAct v3 at 68.4% with Opus 4.6) would help. As stated, this is folk knowledge dressed as fact.
- **"OpenHands SDK paper ... reports 72% on SWE-Bench Verified with Claude Sonnet 4.5 and extended thinking"** (§2). I could not find this number in the arXiv abstract (2511.03690). Either it's in the paper body and needs a page citation, or the number is wrong. If the number came from a blog post, cite the blog post. Currently it's an unsourced specific claim.
- **"Roughly 80% of the technical lineage"** (§Conclusion). This is a rhetorical flourish, not a measurement. Either back it out, or define what "technical lineage" means and how 80% was estimated. As written, it is the kind of sentence a hostile reviewer flags as overclaim.
- **"Mid-2026 there is no peer-reviewed paper that lands cleanly on N independent watchers cooperating on a real project's quality surface"** (§6). Unfalsifiable as written. The review never defines "cleanly," and the negation-of-existence claim is exactly what a citation-graph walk should pressure-test. I suspect AgentAuditor, AgentSpec, and the program-repair-in-CI literature collectively *do* cover this; the review just didn't find them.

### 1.5 Mischaracterized or under-credited prior work

- **Reflexion**: the review describes its architecture as "Actor, Evaluator, Self-Reflection." That's accurate, but the review under-credits Reflexion's *episodic memory buffer* contribution, which is exactly the analog of the plan's work-log persistence. The plan's "continuity between ticks lives in the file" is Reflexion's verbal-RL pattern, full stop. Give Reflexion more credit, not less.
- **SWE-agent**: the review correctly identifies the ACI argument but does not credit the team for the *broader research-direction* contribution — Yang et al. essentially defined the modern coding-agent paradigm. The plan's BaseWatcher prompt-builder pattern is downstream of this whether or not the plan's authors realized it.
- **CodaMosa**: under-credited. The hybrid evolutionary+LLM pattern is more general than the review suggests; Lemieux et al. essentially defined "LLM as escape valve for stuck classical algorithms," a pattern the plan implicitly reuses in the coverage-driven scenario growth (`pr-c2397e2`).

### 1.6 Citation accuracy spot-checks

- **SWE-Bench authors** (§1, ref list): "Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan 2024" — verified. Correct first-author and order.
- **SWE-agent authors** (§2, ref list): "Yang, Jimenez, Wettig, Lieret, Yao, Narasimhan, Press" — verified. Correct.
- **Reflexion authors**: review lists "Shinn, et al." but the full list (Shinn, Cassano, Berman, Gopinath, Narasimhan, Yao) belongs in the references for a serious literature review.
- **Sainz et al. title**: review writes "NLP Evaluation in trouble: On the Need to Measure..." The actual title is "NLP Evaluation in Trouble: On the Need to Measure LLM Data Contamination for Each Benchmark." Capitalization is wrong in §5 prose; the reference entry has it as "Trouble" (correct). Minor but check.
- **ImpossibleBench authors**: review lists "Wu, Ziqian et al. 2025." Verified authors are **Ziqian Zhong, Aditi Raghunathan, Nicholas Carlini**. The review attributes the paper to "Wu" — this is a real error. The first author is Zhong, not Wu. Fix.
- **ProgramBench arXiv:2605.03546**: I was prepared to flag this as a hallucination based on the prompt's hint, but the paper *does* resolve — title "ProgramBench: Can Language Models Rebuild Programs From Scratch?", authors include John Yang, Kilian Lieret, Ofir Press et al. It's a real paper. The "2605" YYMM format (May 2026) checks out for today's date. Verified — not a hallucination. The review's characterization (200 tasks, offline-only, cleanroom) matches the abstract; the "Claude Opus 4.7 with mini-swe-agent tops the leaderboard" claim is not verified from the abstract and should be sourced (programbench.com leaderboard URL).
- **OpenHands SDK**: arXiv:2511.03690 exists, authors verified, but the "72% on SWE-Bench Verified with Sonnet 4.5 + extended thinking" specific number is *not* in the abstract. Either find the in-paper page reference or remove the figure.
- **NIST CAISI**: web series confirmed (nist.gov/caisi/cheating-ai-agent-evaluations/). Characterization matches. Good.

### 1.7 Industry vs. academic distinction

This is *exactly* the place where the review papers over thin coverage. §6 and §7 both lean on "industry-flavored but architecturally informative" framing. That phrase is doing a lot of work. The honest version is: "we did not find academic work, but a thorough search of CI-bot literature, supervisor-worker patterns, and LLM-test-double papers would likely surface peer-reviewed work we missed." The review should either (a) actually do that search and report findings, or (b) name the search terms it ran and admit they were limited. As is, "thin" is a confession of incomplete search dressed as a finding about the field.

### 1.8 Load-bearing claims lacking citation

- "OpenHands has become the de facto baseline for SWE-Bench Verified." Needs leaderboard URL or survey citation.
- "Claude Opus 4.7 with mini-swe-agent currently tops the leaderboard" (ProgramBench). Needs programbench.com URL with snapshot date.
- "Monitor sensitivity in ImpossibleBench's complex-cheating setting was 42-50%" — cited to ImpossibleBench, but the abstract I fetched does not give these numbers; the review needs to cite the specific table or section of the paper. Otherwise it's a specific-sounding number unsupported by the citation as given.
- "Devin first to claim a fully autonomous 'junior engineer' framing" — cited to a Cognition blog post URL, fine, but the "first" claim is unsupportable without a date check against contemporaneous tools.
- "OSS-Fuzz as the corpus-grows-over-time analog" — should be cited (Serebryany 2017 USENIX or the OSS-Fuzz GitHub).

### 1.9 Empirical data that complicates the framing

- **ImpossibleBench's monitor sensitivity numbers** (42-50% on complex multi-file cheating) are actually *worse* than the review's spin suggests for the plan. If the best published LLM-as-auditor is at 42-50% on simpler cheats than the plan's runtime-internet case, the plan's integrity audit is starting from a weak base rate. The review notes this but soft-pedals: "a sobering data point" understates the load on the audit design.
- **Huang et al. 2023**: LLMs *cannot reliably self-correct reasoning without external feedback*. The QA scenario quality supervisor is exactly self-correction with the same model. The review's "Self-Refine failure modes are well-documented" hand-wave should become a concrete citation with a concrete number (Huang et al. report performance often *degrades* after self-correction, not just stagnates).
- **Pan et al. 2024 reward-hacking-in-self-refinement**: identical-context generator/evaluator pairs reward-hack spontaneously. The supervisor's "default 2 amendments per scenario" cap is the right instinct but the literature suggests bounded iteration alone isn't enough; *context separation* matters more. The review's framing doesn't surface this.

### 1.10 Specific challenges from the prompt

**Q1: Is ImpossibleBench the closest peer?** Partly. NIST CAISI is closer for the *runtime-internet* threat model. Anthropic 2025 alignment-auditing-agents is closer for the *supervisor-architecture* angle. ImpossibleBench is closest only on the narrow "LLM exploits the scoring surface" axis.

**Q2: Is watcher-architecture academic literature thin?** No, not as thin as the review claims. AgentSpec, AgentAuditor, the program-repair-in-CI literature (Sapfix, Getafix, and academic follow-ups), and SkillProbe (arXiv 2603.21019) are all relevant. The review gave up too easily.

**Q3: Is runtime-with-internet integrity audit underexplored?** Less than the review claims. NIST CAISI explicitly handles the case. Anthropic's auditing-agents post handles it. The novelty is in the *specific design* (allowlist + post-run audit + structured `audit.md`), not in the *area*.

**Q4: 80% of technical lineage claim**: indefensible as a measurement. Rhetorical flourish. Cut it.

**Q5: Citation graph walked?** No. The 10-reference set is a first-tier seed list. A real citation walk would have surfaced Huang et al. 2023 (which cites Self-Refine and Reflexion), Pan et al. 2024 (cites Reflexion), Agentless and AutoCodeRover (cite SWE-Bench), and the post-ImpossibleBench cheating-detection follow-ups. The review stopped at the seed papers.

**Q6: ProgramBench arXiv:2605.03546 hallucination?** No — verified real. Authors and title match. Date format checks out for May 2026.

**Q7: Yang vs. Jimenez author order?** Verified correct as written: Jimenez first-authors SWE-Bench, Yang first-authors SWE-agent. The review has these right.

**Q8: Industry-heavy sections honest about uncertainty?** Partially. §6 and §7 admit thinness but don't admit incomplete search. That's the gap.

---

## Block 2 — structure and readability

### 2.1 "Non-expert readable"? Mostly yes, with passages that fail

The review claims accessibility for a software engineer reading the plan. Passages that fail:

- **§1, "agent-computer interface"** — used without definition the first time. The review later (§2) defines it implicitly via SWE-agent. Reorder: define ACI on first use, then refer back.
- **§4, "actor-critic pattern"** — used at the end of §4 without explanation. A reader who hasn't done RL won't connect "actor" to "implementation watcher" without help.
- **§5, "edit-distance and AST-based plagiarism detection"** — fine for an engineer, but the review never says *why* AST plagiarism detection is the right tool for contamination. One sentence would fix it.
- **§5, "Inspect-based transcript review"** — "Inspect" is named as if known. It's AISI/Anthropic's eval framework; the first mention should say so.
- **§4, "verifier-guided generation"** — name-dropped without citation or definition.

### 2.2 Verbose vs. needs-more-space

**Overly verbose:**
- §1 paragraphs 1-2 spend too long on HumanEval/MBPP history before getting to what the plan actually uses. Compress to one paragraph.
- §2's Devin paragraph is essentially "no paper exists." That's two sentences, not a paragraph.
- §Conclusion repeats the §5 framing about ImpossibleBench monitor sensitivity. Pick one place.

**Needs more space:**
- §5's *threat model* — the distinction between pretraining contamination and runtime contamination is the load-bearing argument and deserves a paragraph of its own with an example.
- §6's *priority-without-state* bet — one sentence at the end. This is one of the plan's most-distinctive design choices and deserves a paragraph contrasting with the Dependabot/Renovate state machines.
- §3's *coverage-driven scenario growth* analogy to Fuzz4All's autoprompting loop — interesting and crisp, but underdeveloped. Two more sentences.

### 2.3 Repetition

**Unnecessarily repeated:**
- ImpossibleBench's 42-50% sensitivity figure appears in §5 and again in the Conclusion. Once is enough.
- "Roughly 80% of the technical lineage" framing is signaled in the intro and restated in the conclusion. Cut from one.

**Should be repeated but isn't:**
- The "compounding regression library" thesis (§3) — this is the plan's most-distinctive design claim and only appears once. A callback in §Conclusion would help.
- The "runtime contamination is a turn-by-turn decision" framing (§5) — should be foreshadowed in the intro.

### 2.4 Structural changes

- **Merge §6 and §7** into "Operational Infrastructure (industry-heavy)." Both are thin academic / heavy industry; combining them lets the review be honest in one place rather than apologetic in two.
- **Promote the integrity-audit threat model** (currently buried mid-§5) to a stand-alone subsection. It's the plan's biggest research bet, per the review's own admission, and it deserves visual prominence.
- **Add a "Where this plan sits" diagram** at the start of §Conclusion (see below).

### 2.5 Section flow

Transitions are mostly fine. Two abrupt ones:
- §4 → §5 jump from self-refine loops to contamination is harsh. A connecting sentence about "the same self-critique pathology shows up when the critic is an integrity auditor" would bridge.
- §5 → §6 jumps from "integrity audit literature is thin" to "watcher architecture sits in industry." The reader feels the topic-shift. A bridge: "Beyond the integrity question, the plan's *shape* — three cooperating watchers — has its own literature." would help.

### 2.6 Hooks and punchy lines

Hooks the review needs:

- **Open §1** with the consequence, not the history. "The capstone PR rejects ProgramBench's offline assumption. To know whether that's a research bet or a research blunder, you have to know what benchmarks measure and why each generation was designed against the previous." — that's the hook. Then the history.
- **Open §5** with the failure mode. "If the agent quietly googles the answer, the score is theater. Section 5 is about how the literature catches that." Currently §5 opens with "This is the load-bearing literature for the capstone PR" which is true but flat.
- **Open §Conclusion** with the bet. "The plan's biggest research bet is that runtime-with-internet integrity audits can be built well enough to be credible." The conclusion as written buries this in a four-way-intersection metaphor.

### 2.7 Figures, tables, diagrams

Three additions would substantially help:

1. **Benchmark comparison table** for §1: rows = HumanEval, MBPP, SWE-Bench, SWE-Bench Verified, SWE-Bench Pro, LiveCodeBench, BigCodeBench, ProgramBench; columns = year, network access, contamination defense, task granularity, evaluator type. The prose currently asks the reader to construct this table mentally.
2. **Plan-placement diagram** for §Conclusion: a 2D space (axes: "online vs offline" and "static benchmark vs continuous") with prior work plotted (SWE-Bench, ProgramBench, OSS-Fuzz, Dependabot) and the plan's three-watcher loop placed.
3. **Self-critique pattern evolution** for §4: Self-Refine → Reflexion → ChatUniTest's GVR loop → the plan's QA quality supervisor. Boxes and arrows, no prose required.

---

## Concise verdict

Useful map; weak citation-graph walk. The Conclusion overclaims completeness ("80%"), the integrity-audit section underclaims prior art (NIST is closer than admitted; Anthropic alignment-auditing-agents and AgentAuditor are missing), and the self-refinement section omits its single most important rebuttal paper (Huang et al. 2023). At least one author attribution is wrong (ImpossibleBench is Zhong et al., not Wu et al.). At least one specific empirical claim (OpenHands SDK at 72% on SWE-Bench Verified) is not in the cited paper's abstract and needs a page citation or removal. Sections 6 and 7 lean on "industry-heavy" as cover for incomplete search; the search should be redone or the cover should be made honest.

Strongest section: §3's *compounding regression library* contrast with CodaMosa/Fuzz4All.
Weakest section: §6, where "academic literature is thin" is asserted, not earned.

This review took roughly 30 minutes of citation-checking to write. A second cycle should be harder.
