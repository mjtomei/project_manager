# Review Response — Cycle 6 (regression-loop literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_6_REGRESSION.md`

Cycle 6 surfaced 30 findings (16 substantive, 14 phrasing). The substantive yield is concentrated in **Block 1** (8) — primarily six candidate prior-art citations from the citation-graph walk — and **Block 3** (8 accessibility re-glossings). Phrasing rolls into the edit pass.

This response handles the six prior-art candidates first, since they are the load-bearing claims and the methodology principle ("narrow the contribution; don't collapse it") applies most acutely there. Each candidate was verified against its source abstract before being accepted. **Two reviewer claims overstated the prior art's scope; the response narrows or rejects those framings.**

---

## Bucket A — verified prior-art candidates (B1.1–B1.5)

### A1. SWE-CI (Chen et al., arXiv:2603.03823) — B1.1

**Decision: cite with corrected scope. The reviewer's §7-reframing claim is overstated.**

**Verbatim abstract (relevant excerpt):**

> "To bridge this gap, we propose SWE-CI, the first repository-level benchmark built upon the Continuous Integration loop, aiming to shift the evaluation paradigm for code generation from static, short-term functional correctness toward dynamic, long-term maintainability. The key insight is simple: Maintainability can be revealed by tracking how functional correctness changes over time. The benchmark comprises 100 tasks, each deriving from a real-world code repository with a development history spanning an average of 233 days and 71 consecutive commits."

**What SWE-CI actually does.** 100-task offline benchmark reconstructed from real repositories' commit histories (avg 233 days, 71 commits). The agent under test must "systematically resolve these tasks through dozens of rounds of analysis and coding iterations" against a *historical* CI loop. SWE-CI does **not** include live-internet access, runtime sandbox, or any continuously-running watcher component. "Continuous" in SWE-CI refers to *continuous integration over commit history*, not *continuous runtime against a live project*.

**What the plan does that SWE-CI doesn't.**

- Operates against a *live* project being developed in real time, not a frozen snapshot of historical commits.
- Authors *new* regression tests (`pr-2680fbf`) rather than only re-running the historical test suite.
- Integrates a transcript-audit verdict (`pr-e2b7fdf`) into the merge gate.
- Is a deployable tool, not a benchmark.

**Reviewer overstatement.** B1.1 claims SWE-CI is "the academic peer for the live-internet + continuous quadrant in §7." That conflates two senses of "continuous." SWE-CI sits on the **maintainability-over-commit-history** axis; the plan sits on the **live-runtime + continuous-watcher** axis. They share the *temporal-iteration* observation that one-shot benchmarks miss long-term properties, but the quadrant in §7 is the live-runtime quadrant, which SWE-CI does not populate. The §7 framing does not collapse against SWE-CI; it narrows.

**Replacement framing for §7 (narrowed, not collapsed):**

> "SWE-CI (Chen et al. 2026, arXiv:2603.03823) is the closest published peer on the *temporal-iteration* axis — a 100-task benchmark that evaluates agent maintainability across an average of 71 consecutive commits per repository. It frames maintainability as the dependent variable, as the plan does, but evaluates it offline against historical commit traces rather than against a live runtime. The plan's §7 quadrant — *live-runtime continuous watcher with internet-allowed sandbox* — remains sparsely populated; SWE-CI populates the adjacent *offline-replay continuous* quadrant. The contribution is the operational delivery of the continuous-maintenance shape against a live project, with new-test authoring and audit-gated merge that an offline benchmark does not exercise."

---

### A2. RepairAgent (Bouzenia, Devanbu, Pradel — arXiv:2403.17134, ICSE 2025) — B1.2

**Decision: cite. Reviewer framing is accurate.**

**Verbatim abstract (relevant excerpt):**

> "This paper introduces RepairAgent, the first work to address the program repair challenge through an autonomous agent based on a large language model (LLM). … RepairAgent freely interleaves gathering information about the bug, gathering repair ingredients, and validating fixes, while deciding which tools to invoke based on the gathered information and feedback from previous fix attempts. Key contributions that enable RepairAgent include a set of tools that are useful for program repair, a dynamically updated prompt format that allows the LLM to interact with these tools, and a finite state machine that guides the agent in invoking the tools. Our evaluation on the popular Defects4J dataset demonstrates RepairAgent's effectiveness in autonomously repairing 164 bugs, including 39 bugs not fixed by prior techniques."

**What RepairAgent actually does.** Autonomous LLM-agent program repair with FSM-guided tool selection across three phases (gather bug info / gather repair ingredients / validate fix). Evaluated on Defects4J: 164 bugs repaired, 39 unique. Average cost 270K tokens / 14 cents per bug (GPT-3.5 pricing).

**What the bug-fix watcher (`pr-30588a7`) does that RepairAgent doesn't.**

- Runs as a *watcher tick* against a live project's bug queue, not per-bug invocation on a benchmark.
- Persistent work-log between attempts (RepairAgent's loop is per-bug, no cross-bug state).
- Integrates with the discovery → implementation → review supervisor chain; bug fixes feed back to the discovery supervisor's queue.
- Does not use FSM prompt orchestration; uses Claude Code's built-in tool loop.
- Not validated against Defects4J or any standard APR benchmark.

**Replacement framing for §4 paragraph 3 (per reviewer suggestion, lightly tightened):**

> "The plan's bug-fix flow reruns APR's playbook with the LLM as generation engine, and is closest on architectural axis to RepairAgent (Bouzenia, Devanbu, Pradel — ICSE 2025, arXiv:2403.17134) — same outer loop (localize → analyze → generate → verify → iterate), without RepairAgent's finite-state-machine prompt orchestration or Defects4J validation. `pr-30588a7` is RepairAgent's design at watcher-tick cadence rather than per-bug cadence, with a persistent work log between attempts and integration into the discovery → implementation → review supervisor chain."

---

### A3. SWE-Bench Pro arXiv paper (arXiv:2509.16941) — B1.3

**Decision: cite. Reviewer framing is accurate.**

**Verbatim abstract (relevant excerpt):**

> "We introduce SWE-Bench Pro, a substantially more challenging benchmark that builds upon the best practices of SWE-BENCH … SWE-BENCH PRO contains 1,865 problems sourced from a diverse set of 41 actively maintained repositories spanning business applications, B2B services, and developer tools. … Problems in the held-out and the commercial set are not publicly accessible, but we release results on the commercial set."

**What it adds.** 1,865 problems, 41 repos (11 public / 12 held-out / 18 commercial), contamination-resistant, long-horizon (hours-to-days for a professional engineer), human-verified.

Note: the reviewer's specific resolve-rate claims (GPT-5 23.3%, Claude Opus 4.1 23.1%) did not appear in the abstract I fetched. The verbatim arXiv abstract does not anchor those headline numbers. The lit review should cite the paper for the *benchmark design and scale*, not for the specific resolve rates unless those numbers are independently verified against the paper body. **Edit will fetch the body or OpenReview submission to confirm before citing the percentages.**

**Replacement for §1 (sourcing tightening):**

> "Scale AI / OpenAI's SWE-Bench Pro (Deng, Da, Pan et al. 2025, arXiv:2509.16941) is the published successor benchmark — 1,865 contamination-resistant problems across 41 repositories, with long-horizon enterprise-style tasks human-verified for resolvability. Frontier models' resolve rates on this benchmark anchor §1's claim that long-horizon software work is far from solved; specific percentages cited against the paper body."

---

### A4. RHB (Thaman, arXiv:2605.02964, 2026-05-03) — B1.4 first half

**Decision: cite. Reviewer framing is accurate.**

**Verbatim abstract (relevant excerpt):**

> "We introduce the Reward Hacking Benchmark (RHB), a suite of multi-step tasks requiring sequential tool operations with naturalistic shortcut opportunities such as skipping verification steps, inferring answers from task-adjacent metadata, or tampering with evaluation-relevant functions. … We evaluate 13 frontier models from OpenAI, Anthropic, Google, and DeepSeek. Exploit rates range from 0% (Claude Sonnet 4.5) to 13.9% (DeepSeek-R1-Zero), varying sharply by post-training style. … We identify six exploit categories and find that 72% of reward hacking episodes include explicit chain-of-thought rationale."

**What RHB actually measures.** Exploit *rates* (not detection rates) — how often frontier models exploit tool-use shortcuts when given the opportunity. Threat shapes overlap with the capstone's lookup-detection threat (metadata-inference shortcuts are structurally close to runtime-internet lookup).

**Reviewer claim partial overstatement.** B1.4 says RHB "fills the §6.3 'audit sensitivity is open question' gap." RHB measures **base exploit rates**, not **audit sensitivity** (detection rates against those exploits). The audit-sensitivity gap is filled by **A5** (TRACE / contrastive-analysis paper), not RHB. RHB gives the *base rate* the audit's ROC has to clear — useful, but a different number. The lit review should cite RHB as the source for the base-rate anchor, not as the answer to the detection-sensitivity question.

**Replacement framing for §6:**

> "RHB (Thaman 2026, arXiv:2605.02964) measures shortcut-exploit rates across 13 frontier models on multi-step tool-use tasks: 0% (Claude Sonnet 4.5) to 13.9% (DeepSeek-R1-Zero), with 72% of exploits accompanied by chain-of-thought rationale. RHB anchors the *base rate* against which the capstone's audit must demonstrate sensitivity; it does not itself measure detection performance."

---

### A5. TRACE / Reward Hack Detection contrastive (arXiv:2601.20103) — B1.4 second half

**Decision: cite. Reviewer framing is accurate; this is the paper that genuinely addresses the §6.3 "audit sensitivity is open question" framing.**

**Verbatim abstract (relevant excerpt):**

> "We propose a novel taxonomy of reward exploits spanning across 54 categories and introduce TRACE (Testing Reward Anomalies in Code Environments), a synthetically curated and human-verified benchmark containing 517 testing trajectories. Unlike prior work that evaluates reward hack detection in isolated classification scenarios, we contrast these evaluations with a more realistic, contrastive anomaly detection setup on TRACE. Our experiments reveal that models capture reward hacks more effectively in contrastive settings than in isolated classification settings, with GPT-5.2 with highest reasoning mode achieving the best detection rate at 63%, up from 45% in isolated settings on TRACE."

**What TRACE actually does.** Measures **detection sensitivity** of LLM-judge auditors on a 517-trajectory benchmark of code-environment reward hacks. Best detection rate: 63% (GPT-5.2, contrastive setting). This is the paper the §6.3 "open question" sentence loses to.

**What the capstone audit does that TRACE doesn't.**

- Runs against a runtime-internet-lookup threat specifically (not the full 54-category taxonomy).
- Operates as a *merge-gate* in a deployed loop, not a benchmark evaluation.
- Mixes single-transcript and across-trace signals (TRACE is single-transcript classification).
- The allowlist-vs-trace boundary check is a structural mechanism TRACE does not include.

**Replacement framing for §6.3 (resolving the "open question" sentence):**

> "The audit's sensitivity on the runtime-internet-lookup variant specifically is unmeasured; the contrastive-analysis literature (Deshpande, Kannappan, Qian 2026, arXiv:2601.20103, TRACE benchmark) gives the nearest available floor: 45–63% detection rate for state-of-the-art LLM judges on code-environment reward hacks, depending on contrastive vs. isolated framing. The capstone's audit job is to demonstrate operating-point sensitivity above that floor on the narrower lookup-detection sub-task."

---

### A6. Introspection Adapters + A3 (alignment.anthropic.com 2026) — B1.5

**Decision: cite Introspection Adapters with narrowing. Drop the "supersede AuditBench" overstatement. A3 is real but tangential to the plan; mention briefly or omit.**

**Verified sources.**

- Introspection Adapters: `https://alignment.anthropic.com/2026/introspection-adapters/` (also arXiv:2604.16812). Announced via Anthropic Fellows tweet on 2026-04-29. Trains LoRA adapters that cause fine-tuned models to self-report their learned behaviors in natural language. Reports state-of-the-art performance on AuditBench (Sheshadri et al. 2026) and can detect covert fine-tuning attacks.

- A3 (Automated Alignment Agent for Safety Finetuning): `https://alignment.anthropic.com/2026/automated-alignment-agent/`. Anthropic Fellows project, posted 2026-03-11. Open-sourced at `github.com/safety-research/A3`. Three-stage pipeline (data-gen agent / finetuning agent / experiment log) that *mitigates* known safety failures via iterative finetuning. Targets sycophancy, political bias, nesting jailbreaks. Achieves 0.2% SFR on political-bias validation set.

**What Introspection Adapters actually does.** A method for *the audited model to self-report* its learned behaviors. IA-equipped investigator agents achieve state-of-the-art on AuditBench. The IA is trained on the auditor side, deployed as a LoRA on the auditee.

**Reviewer overstatement on "supersede."** B1.5 says IA "supersedes AuditBench's investigator-tool ranking." More precisely: IA achieves SOTA *on* AuditBench (which is a benchmark of 56 models with implanted behaviors). It doesn't supersede the *benchmark*; it sets a new top score on it. The lit review's §6 currently cites AuditBench as the precedent for investigator-tool design — IA is the **latest entry on AuditBench's leaderboard**, not a replacement framework. The "supersede" framing collapses two things that should narrow.

**What A3 does.** Automated *finetuning* to *fix* known safety failures, with an experiment log for cross-run memory. This is an alignment-research tooling system, not an audit system. Its relation to the capstone is at the meta-level (both are agentic alignment-research loops with logs) but not on the audit axis the lit review is anchoring. **Decision: omit A3 from §6, or add a single-sentence pointer in a footnote.** It is not load-bearing for §6's argument.

**What the capstone audit does that IA doesn't.**

- The capstone's audit is *post-run transcript-walk* over a deployed agent's actions. IA is *model-side self-report* about learned behaviors. Different artifact: IA examines the model's weights / fine-tuning history; the audit examines the run trace.
- IA presupposes auditor access to the model's training process; the capstone's audit operates without that access.
- The capstone targets runtime-internet-lookup specifically; IA targets implanted-behavior detection generally.

**Replacement framing for §6.3 (narrowed, not collapsed):**

> "Anthropic's 2026 Introspection Adapters work (Anthropic Fellows 2026, alignment.anthropic.com/2026/introspection-adapters/; arXiv:2604.16812) sets the current state-of-the-art on AuditBench: a LoRA adapter trained on the auditor side that causes auditee models to self-report their learned behaviors in natural language. IA addresses *model-side* behavior disclosure; the capstone's audit operates on the *run-time transcript* without requiring access to the model's training process. The two methods are complementary — IA tells the auditor what the model learned; the capstone's audit tells the auditor what the model did on this run. Whether to integrate IA-style introspection into the capstone is future work."

---

## Bucket B — other substantive findings (B1.6, B1.7, B1.8, B2.1, B2.2, B3.1–B3.8)

### B1.6 — "Compounding" framing still under-specified

**Agree, commit.** Six cycles is enough. The next-cycle obligation is the falsifiable prediction. Pick **bugs-found-per-week-of-runtime across four watcher-week samples** as the operational definition for "compounding" — it's the cleanest single signal, and the discovery supervisor already logs bug-find events. The other candidate (coverage-delta per drafted regression that survives one supervisor verdict) is a secondary metric, not the primary commitment.

**Edit**: replace §5/Conclusion's hedged "operational definition future work" with: "Compounding will be operationally defined as bugs-found-per-week-of-runtime measured across four consecutive watcher-week samples on a live project, with a positive trend (week-over-week increase ≥ 5%) as the threshold. This is the next-cycle measurement obligation."

### B1.7 — ProgramBench caveat not in the matrix

**Agree.** Add an in-matrix footnote marker. The matrix currently presents ProgramBench as on par with SWE-Bench; the caveat appears three paragraphs later. Add "ProgramBench (preliminary; smaller evidence base — see surrounding text)" to the matrix entry.

### B1.8 — Bothsidesist contribution-sentence

**Agree.** Replace per reviewer's suggested rewrite: "If the audit's recall on runtime-internet-lookup is below 50% in pilot, the capstone reverts from a merge gate to a human-review trigger. That threshold is the falsifiable claim the capstone PR (`pr-e2b7fdf`) has to clear."

### B2.1 — Split §6.3 into §6.3 / §6.4

**Agree.** §6.3 → single-transcript + across-traces audit pipelines (NIST CAISI, Inspect Scout, Meerkat, IA). §6.4 → human-review framing + adjacent measurements (overt-saboteur, automated-auditing, ImpossibleBench, Liars' Bench, RHB, TRACE). The new prior art from A4/A5 lands naturally in §6.4.

### B2.2 — Cut the terms-paragraph

**Agree.** Replace lines 33–35 with a one-sentence pointer at §1 opening: "(Terms like LLM, watcher, PR, capstone are glossed in the Appendix on first use.)"

### B3.1–B3.8 — Accessibility re-glossings

**Agree, apply per reviewer's specific replacement sentences.** All eight findings include concrete rewrites; the edit pass applies them verbatim with light tightening:

- B3.1 "auto-sequence" → use the longer plain-English gloss the reviewer proposed.
- B3.2 "execute-only permissions on the binary" → "the agent can run the reference program but cannot inspect its source code or peek at its internals."
- B3.3 Add CTF gloss inline on first use in §6.
- B3.4 Re-anchor "allowlist" in §6.2.
- B3.5 Gloss "fail-to-pass rate" in §3.1.
- B3.6 Re-anchor "process supervision" with the math-word-problem concrete example.
- B3.7 Cut the Persona Vectors forward-pointer sentence (option (a) — clean cut, not worth the gloss budget for a forward-looking pointer).
- B3.8 Convert §6.2's five-clause sentence to a bulleted list.

---

## Bucket C — phrasing / prose (B3.9, B3.10, B4.1–B4.8)

Roll up into the edit pass. Notable items:

- B3.9 Add eval-aware-sabotage gloss.
- B3.10 Cut "(APR)" acronym — use "automated program repair" the two times it appears.
- B4.1 Cut the redescription paragraph after the watcher-hierarchy diagram (the diagram labels carry the load).
- B4.2 Split §1 paragraph 4 (the 250-word one).
- B4.3 Replace 3 of 5 "structurally" usages with "architecturally," "by design," and "in the same shape."
- B4.4 Audit "shape" — replace vague usages with "design" or "pattern."
- B4.5 Replace "informally" in §7 with the operational description.
- B4.6 Cut the three deadwood lines (41, 56, 264) per reviewer's exact rewrites.
- B4.7 Cut emphasis-italics in §6.3; reserve italics for new-term-being-defined only.
- B4.8 Replace "still-actively-shipping" with the longer plain rewrite.

---

## Edits checklist

1. **§7 — add SWE-CI** with the narrowed framing (Bucket A1). Do NOT collapse the live-runtime quadrant; SWE-CI occupies the offline-replay-continuous adjacent quadrant, not the live-runtime one.
2. **§4 — add RepairAgent** with the narrowed framing (Bucket A2). `pr-30588a7` description narrows to "RepairAgent design at watcher-tick cadence with persistent work-log + supervisor-chain integration."
3. **§1 — add SWE-Bench Pro arXiv:2509.16941** alongside the Scale blog (Bucket A3). Verify resolve-rate numbers against the paper body before citing percentages.
4. **§6 — add RHB (A4)** as the base-rate anchor, not as the audit-sensitivity answer.
5. **§6.3 — add TRACE (A5)** as the answer to the audit-sensitivity question; rewrite the "open question" sentence to cite the 45–63% floor.
6. **§6.3 — add Introspection Adapters (A6)** with the narrowed "complementary, not superseded" framing. Drop A3 from §6 (tangential; optional footnote).
7. **§5/Conclusion — commit to the compounding metric** (Bucket B1.6): bugs-found-per-week-of-runtime, four watcher-week samples, ≥5% trend.
8. **§1 matrix — annotate ProgramBench** with the preliminary-evidence footnote (B1.7).
9. **Conclusion — replace bothsidesist sentence** with the 50% recall threshold (B1.8).
10. **§6.3 → §6.3 + §6.4 split** (B2.1). New prior art lands in §6.4.
11. **Cut Intro terms-paragraph** (B2.2); replace with one-sentence pointer.
12. **Apply B3.1–B3.8 accessibility rewrites** verbatim with light tightening; cut the Persona Vectors forward-pointer per B3.7 option (a).
13. **Apply Bucket C phrasing nits** per reviewer's exact rewrites.

---

## Plan-owner items

- `pr-30588a7` (bug-fix watcher) description should narrow against RepairAgent — see A2 replacement framing. The plan's PR description currently does not name RepairAgent.
- `pr-e2b7fdf` (capstone audit) should commit to the ≥50% recall threshold per B1.8 as the falsifiable success criterion.
- Discovery supervisor should be the source of the bugs-found-per-week metric per B1.6's compounding commitment.

---

## Convergence note

Cycle 6 yielded 16 substantive findings versus Cycle 5's 5. Yield is *up*, not down — driven by recent publications (SWE-CI March 2026, RHB May 2026, TRACE January 2026, IA April 2026) that post-date Cycle 5's walk. The methodology says three cycles is typical; this is six and the prior-art yield is still nontrivial.

**However**, of the six new prior-art candidates Cycle 6 surfaced, **two were partially overstated** (SWE-CI on the §7-quadrant framing; IA on the "supersede AuditBench" framing) and one (A3) is tangential enough to drop. Three were clean accepts. This is the methodology's "verify before incorporating" pattern paying off — had the response taken the reviewer's framings at face value, §7 would have collapsed against SWE-CI when SWE-CI is actually on a different axis, and §6 would have over-rotated toward IA when IA is complementary rather than replacement.

**Recommendation per Cycle 6's own close**: one more walk-focused cycle after these are integrated, with explicit seeds for "reward hacking benchmark," "introspection adapter," "continuous integration agent benchmark." If yield drops below 2 substantive misses, stop. This response cycle is **mostly cite-additions with narrowing** (6 new citations with replacement contribution statements) rather than framing-and-prose work — though it carries 14 phrasing/accessibility nits that will land in the same edit pass.
