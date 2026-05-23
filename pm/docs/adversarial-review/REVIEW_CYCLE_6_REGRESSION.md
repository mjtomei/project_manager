# REVIEW CYCLE 6 — Literature Review: Autonomous Regression and Bug-Fix Loop

Reviewer: blind Cycle 6. Date: 2026-05-15. Artifact: `pm/docs/literature-review.md` (~11,143 words). Target audience for Block 3: non-developer evaluator (PM, adjacent researcher, hobbyist).

---

## Block 1 — Substance

### B1.1 [SUBSTANTIVE — load-bearing miss] SWE-CI (Chen et al. 2026, arXiv:2603.03823) is the most directly competing benchmark and is not cited

A March 2026 paper, **SWE-CI: Evaluating Agent Capabilities in Maintaining Codebases via Continuous Integration** (Chen, Xu, Wei, Chen, Zhao, Sun Yat-sen University / Alibaba, arXiv:2603.03823, 2026-03-04) describes itself as "the first repository-level benchmark built upon the Continuous Integration loop, aiming to shift the evaluation paradigm for code generation from static, short-term functional correctness toward dynamic, long-term maintainability." Its core principle: "Maintainability can be revealed by tracking how functional correctness changes over time." 100 tasks, average development history of 233 days and 71 consecutive commits per task.

This is the closest published peer to the plan's *continuous-loop* framing — the lit review's most-defended novelty axis in §7 ("upper-right quadrant — live internet and continuous — sparsely populated"). SWE-CI is precisely that quadrant.

**What SWE-CI actually does** (from abstract): benchmark of 100 repositories evaluated as a CI-loop time series — agent must keep a codebase functional across 71 consecutive commits on average. The DV is functional-correctness drift over a sequence, not single-shot resolution.

**What the plan does that SWE-CI doesn't**: (a) operates *inside* a running project rather than as a snapshot benchmark — the watchers run live against the project being developed; (b) authors new regression tests rather than only running existing ones; (c) integrates a transcript-audit verdict into the merge gate. The plan is a *tool*, SWE-CI is an *evaluation* of tools.

**Replacement contribution statement for §7**: "The plan's distinctive quadrant — live-internet + continuous — is not empty as of March 2026. SWE-CI evaluates agent capability on the long-term maintenance task itself; the plan implements that capability as a deployable tool with new-test authoring and audit-gated merge. SWE-CI is the published peer for the continuous-maintenance evaluation shape; the plan is the operational counterpart."

This is the most damaging miss in the review and the one that should have come up in Cycle 5's seed walk on Dependabot/Renovate (no academic peers found) — SWE-CI is the academic peer that was found and not cited.

### B1.2 [SUBSTANTIVE] RepairAgent (Bouzenia, Devanbu, Pradel, ICSE 2025) is missing from §4

§4 cites GenProg (2012), SapFix (2019), Getafix (2019), Self-Debug, Self-Edit. It does not cite **RepairAgent** (arXiv:2403.17134, ICSE 2025), which the abstract describes as "the first work to address the program repair challenge through an autonomous agent based on a large language model." RepairAgent freely interleaves bug-info gathering, repair-ingredient gathering, and fix validation via a finite-state-machine-guided tool loop, and reports 164 Defects4J bugs autonomously repaired including 39 not fixed by prior techniques.

RepairAgent is *the* peer-reviewed direct precedent for the bug-fix watcher (`pr-30588a7`). The plan's reproduce-fix-verify loop is structurally a less-featureful RepairAgent (no dynamic prompt FSM, no Defects4J-style benchmark validation). Replacement framing for §4 paragraph 3: "The plan's bug-fix flow reruns APR's playbook with the LLM as generation engine, and is closest to RepairAgent (Bouzenia et al. 2025, ICSE) on the architectural axis — same outer loop (localize → analyze → generate → verify → iterate), without RepairAgent's finite-state-machine prompt orchestration or its Defects4J validation. The plan's `pr-30588a7` is RepairAgent's design at watcher-tick cadence rather than per-bug cadence, with a persistent work log between attempts."

### B1.3 [SUBSTANTIVE] SWE-Bench Pro's actual published paper (arXiv:2509.16941) is not cited

§1 mentions "Scale AI's SWE-Bench Pro (2025)" but cites no paper. The actual peer-reviewed-style publication is **"SWE-Bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks?"** (arXiv:2509.16941, v2 2025-11-14, OpenReview submission). 1,865 instances across 41 repositories; best models GPT-5 23.3% and Claude Opus 4.1 23.1% — i.e., on long-horizon enterprise-style tasks, frontier models resolve well under a quarter of the work.

This matters because §1 leans hard on OpenAI's blog-post recommendation of SWE-Bench Pro as the successor benchmark. Citing only the recommendation and not the benchmark's own paper is asymmetric — it puts methodological weight on a non-peer-reviewed blog post while the benchmark's own paper exists. Add the arXiv to References and cite resolve rates as the anchor for "frontier models are far from solving long-horizon engineering."

### B1.4 [SUBSTANTIVE] The Reward Hacking Benchmark (Thaman et al., arXiv:2605.02964) and Benchmarking Reward Hack Detection (arXiv:2601.20103) are missing from §6

§6.1–6.3 cite ImpossibleBench (Zhong 2025), AuditBench, Inspect Scout, Meerkat, NIST CAISI for cheating / reward-hacking detection. Two May-2026 and January-2026 papers are absent:

- **Reward Hacking Benchmark (RHB)** (Thaman, arXiv:2605.02964, 2026-05-03): multi-step tool-use tasks with naturalistic shortcut opportunities. 13 frontier models evaluated, exploit rates 0% (Claude Sonnet 4.5) to 13.9% (DeepSeek-R1-Zero). Directly on the threat model the capstone targets (agents exploiting shortcuts including answer-lookup behavior in tool use). Single most relevant published comparison number for the capstone's expected detection rate.
- **Benchmarking Reward Hack Detection in Code Environments via Contrastive Analysis** (arXiv:2601.20103, 2026-01): explicitly studies *detection* of reward hacks in coding agents, not just measurement of hack rates. The peer for "how well can an automated audit catch this?" — which §6.3 says is an open question. The paper exists; cite it.

The lit review's §6.3 close ("The audit's sensitivity is an open question and a measurement obligation, not a known floor") is now wrong as stated: there *are* prior numbers. The sentence should be narrowed to "the audit's sensitivity on the runtime-internet-lookup variant specifically is unmeasured; the contrastive-analysis and RHB literature gives the nearest available floor (0–14% exploit rate observed across frontier models on tool-use shortcut tasks; the audit's job is to be on the high side of the detection ROC against those base rates)."

### B1.5 [SUBSTANTIVE] Anthropic's "A3: Automated Alignment Agent" and "Introspection Adapters" (both 2026) update the precedent set §6 leans on

The lit review cites alignment.anthropic.com's AuditBench (2026-03-10), coding-audit-realism (2026-03-23), Petri 2.0 (2026-01-22), overt-saboteur (2026-01-28), 2025 automated-auditing note. Two more recent and load-bearing pieces on the same blog are absent:

- **Introspection Adapters** (alignment.anthropic.com, 2026): "method for fine-tuning models to self-report their learned behaviors in natural language. Introspection adapters perform best, with the IA-equipped investigator agent substantially outperforming all prior auditing techniques." This *outperforms AuditBench's investigator setup* — the precedent the lit review currently treats as state-of-the-art.
- **A3: Automated Alignment Agent for Safety Finetuning** (alignment.anthropic.com, 2026).

Without these, §6 reads as if AuditBench is the frontier; as of 2026 the frontier moved. Add both to §6.3 with a one-sentence note: "Anthropic's 2026 Introspection Adapters work supersedes AuditBench's auditing-tool ranking — IA-equipped investigators substantially outperform every prior auditing technique. The capstone's audit does not use introspection adapters; whether that is a deliberate choice or a future-work opportunity should be stated."

### B1.6 [SUBSTANTIVE] "Compounding" framing remains under-specified despite Cycle 5's response

§5/Conclusion still treats "durable" vs. "compounding" as a binary with operational-definition future work. The defensible move at this point is to *commit to one falsifiable prediction* the plan would track once implemented. Concretely: pick one — bugs-found-per-week-of-runtime over four watcher-week samples, OR coverage-delta per `pr-2680fbf` drafted regression that survives one supervisor verdict. The current text describes what the metric *would* look like; it does not commit to which one is the next-cycle obligation. Six review cycles is enough — close the loop on the operational definition.

### B1.7 [SUBSTANTIVE] §1's ProgramBench caveat is honest but the row "denial at runtime" in the matrix still privileges ProgramBench's claim

The §1 matrix lists ProgramBench alone in "denial at runtime — no internet in sandbox." The lit review's own caveat says "ProgramBench's evidence base is still thinner than SWE-Bench's." If the matrix is reporting the populated quadrant honestly, ProgramBench should appear there *with the caveat noted in the matrix itself*, not three paragraphs away. Add a footnote-marker to ProgramBench's entry: "ProgramBench (preliminary)" or similar. Otherwise readers skim the matrix without reading the surrounding prose and walk away thinking ProgramBench is a mature benchmark on par with SWE-Bench.

### B1.8 [PHRASING] The Conclusion's "if it fails, it remains the most likely point of failure" is still hedge-rhetoric

Line 262: "if the plan succeeds, the capstone is the most ambitious integration of AISI/NIST-line transcript-audit machinery with a continuous-quality loop; if it fails, it remains the most likely point of failure." This is the kind of bothsidesist sentence that survives review cycles because it offends no one. The contribution claim and the failure-mode claim are the same sentence — that's a tell that one of them is doing no work. Replace with: "If the audit's recall on runtime-internet-lookup is below 50% in pilot, the capstone reverts from a merge gate to a human-review trigger. That threshold is the falsifiable claim the capstone PR (`pr-e2b7fdf`) has to clear."

---

## Block 2 — Structure and Readability

### B2.1 [SUBSTANTIVE] §6.3 is too long for one subsection

§6.3 covers NIST CAISI, Inspect Scout, Meerkat, overt-saboteur, 2025 automated-auditing, ImpossibleBench, Liars' Bench. Seven precedents at varying threat-model proximity, three separate framings (single-transcript / across-traces / human-final-review). Split into §6.3 (single-transcript and across-traces audit pipelines: NIST CAISI, Inspect Scout, Meerkat) and §6.4 (the human-review framing and adjacent measurements: overt-saboteur, automated-auditing, ImpossibleBench, Liars' Bench). The current one-subsection arrangement forces the reader to hold all seven simultaneously.

### B2.2 [SUBSTANTIVE] The Introduction's terms-paragraph (lines 33–35) is filler

"**Terms used throughout — defined in the Appendix.** The vocabulary the review leans on most: …" is a meta-paragraph telling the reader the Appendix exists. The Appendix does its own work. Cut this paragraph. Inline glosses (which the artifact already does) plus a one-sentence pointer at the start of §1 — "(Terms like LLM, watcher, PR, capstone are glossed in the Appendix on first use.)" — accomplishes the same with one sentence instead of three.

### B2.3 [PHRASING] §3.2 is still an awkward orphan

§3.2 is two paragraphs on test-double terminology. It would either go in an Appendix-style sidebar or be absorbed into the §3 intro. As a numbered subsection at the end of §3 it implies parity with §3.1's substantial literature treatment, which it doesn't have.

### B2.4 [PHRASING] The Conclusion is now seven paragraphs and recapitulates much of §6

Conclusion paragraph 4 ("The capstone's contribution is no longer 'a novel post-run audit architecture'…") restates §6.2/§6.3 in compressed form. Either cut paragraph 4 entirely (the §6 prose already makes this point) or cut the equivalent §6.2 prose. Two passes through the same residual-novelty argument is one too many.

---

## Block 3 — Non-Expert Accessibility (load-bearing)

### B3.1 [SUBSTANTIVE] "Auto-sequence chain" usage in §0 and "auto-sequence" appendix entry don't quite match the target reader

Line 35 names "auto-sequence" as a Terms-used entry; the Appendix gloss (line 364) says "a chained sequence of watcher actions, triggered by one keypress or one command, that runs through implementation, review, and QA without further human intervention." The target reader does not have "watcher actions" as a stable referent — they have "watchers" from the prior gloss but not "watcher actions." Replace appendix gloss with: "a sequence of automated steps — write the code, review it, run the tests — triggered by a single keystroke and running without further input. The plan uses this to chain implementation, review, and QA on a new pull request."

### B3.2 [SUBSTANTIVE] "Sandbox" in §1 is glossed in parentheses but the gloss is incomplete

Line 53 glosses sandbox as "an isolated environment that lets the agent reach out to the rest of the computer or the internet only when explicitly allowed." That's good. But "execute-only permissions on the binary" two lines later assumes the reader knows what execute-only permissions are and what a binary is. The target reader does not. Rewrite the trailing clause: "the agent can run the reference program but cannot inspect its source code or peek at its internals."

### B3.3 [SUBSTANTIVE] "Capture-the-flag" / "CTF" in §6 is undefined

§6.2 and §6.3 reference "cybersecurity / CTF agents" and "71 cybersecurity capture-the-flag tasks" without gloss. The target reader does not know what a CTF is. Inline: "capture-the-flag exercises — competitive security puzzles where the goal is to find and exploit a vulnerability in a deliberately weakened program, used here as a benchmark for autonomous agents trying to do the same thing."

### B3.4 [SUBSTANTIVE] "Allowlist" in §1 / §6 is used load-bearingly without definition

The capstone's distinctive mechanism is described as "an allowlist (a written list of which external sources the agent is permitted to consult)" at line 88. Good — but later usages (§6.2 "allowlist-against-trace boundary mechanism," §6.3) treat "allowlist" as if the gloss already locked in. The target reader will have forgotten by §6. One-sentence re-anchor in §6.2: "the capstone's allowlist (the written list of websites and documents the agent is allowed to consult during the evaluation) is the boundary against which every URL in the agent's transcript gets checked."

### B3.5 [SUBSTANTIVE] "Fail-to-Pass rate" in §3.1's TestExplora paragraph is not glossed

Line 122 says "state-of-the-art LLMs reach only a 16.06 percent fail-to-pass rate on the proactive task." The target reader does not know what fail-to-pass means. Gloss inline: "fail-to-pass rate — the share of tasks where the model authored a test that initially fails on the buggy code and then passes on the fixed code, i.e., correctly identified the bug *and* wrote a working check for it. 16.06% means about one in six attempted tasks succeeded on both fronts."

### B3.6 [SUBSTANTIVE] "Process supervision" in §5 is jargon

Line 158: "extends this to *process supervision* — the verifier scores each intermediate reasoning step, not just the final answer." The gloss is there but "the final answer" assumes the reader is thinking of MATH problems with answers. Re-anchor: "...not just whether the final answer was right but whether each step of the reasoning was right. (On math word problems, this means grading the model's working, not just the bottom-line number.)"

### B3.7 [SUBSTANTIVE] "Activation space" / "model-side direction" in §5 is undefined

Line 160 ends with "the kind of artifact a future scenario quality supervisor could probe for directly in evaluating autonomous-loop runs, complementary to Pan 2024's behavioral-emergence finding." The target reader has no anchor for "activation-space direction," "model-side direction," or "probe directly." Either (a) cut the Persona Vectors sentence — it's a forward-looking pointer that earns its keep only for the model-internals reader; or (b) gloss: "Persona Vectors maps internal numeric patterns in the model that correlate with traits like sycophancy. A future supervisor could check those patterns directly rather than only observing the model's outputs. This is mentioned as a future direction, not part of the current plan."

### B3.8 [SUBSTANTIVE] §6.2's "the audit problem decomposes into a structural setup plus three contributions…" reads as a list inside a paragraph

The five-element setup (lines 188–189) packs into one long sentence: "the sandbox lets the agent reach the open internet… the agent has reason to peek… a single stray click can taint everything… the trace records every action but labels none… the grader sees only the final answer." Convert to a bulleted list. The target reader cannot hold five clauses across one semicolon-chained sentence.

### B3.9 [PHRASING] "Eval-aware sabotage" and "subtle sandbagging" in §6.3 are explained but the explanation arrives after the term

Line 212: "overt sabotage is the easy case — eval-aware sabotage and subtle sandbagging (the model deliberately underperforming so its true capabilities are not measured) remain open problems." Sandbagging is glossed, eval-aware-sabotage is not. Add one clause: "eval-aware sabotage (where the model behaves well only when it suspects it's being tested) and subtle sandbagging..."

### B3.10 [PHRASING] Acronyms — APR, AST, ACI

§4 introduces "automated program repair (APR)" but uses APR only twice; the spell-out is enough, the acronym is overhead. Cut "(APR)" and just use "automated program repair." §2 already glosses ACI; §2 says "AST" with gloss — fine.

---

## Block 4 — Writing Quality and Prose Craft

### B4.1 The Introduction's "Watcher hierarchy at a glance" diagram has stale arrow labels

The diagram labels (lines 16–31) say "files PR (bug or improvement)" but the next paragraph (line 33) re-describes each arrow's payload in different words ("the discovery supervisor passes a bug or improvement description; the implementation watcher passes a candidate diff"). Either delete the redescription paragraph or remove the labels from the diagram and let the paragraph carry the load. The duplication is a tell that one of them was added late and the other not pruned.

### B4.2 §1 paragraph 4 (lines 51–53) is the longest single paragraph in the document

Six sentences, ~250 words, four named benchmarks (SWE-Bench, SWE-agent, SWE-Bench Verified, SWE-Bench Pro, SWE-Bench Multimodal), one extended methodological aside on ACI. Split: one paragraph on SWE-Bench + ACI; one paragraph on the Verified / Pro / Multimodal variants.

### B4.3 Hedge inflation: "roughly," "approximately," "structurally"

The document uses "structurally similar" / "structurally adjacent" / "structurally relevant peer" five times across §3, §4, §5, §6. Each instance is doing slightly different work. Pick a different word for at least three: "architecturally," "by design," "in the same shape," "at the same grain." The repetition makes the prose monotonous and signals that "structurally" has become a filler hedge.

### B4.4 Word choice — "shape"

"Same architecture, different threat" (line 86), "post-run audit shape" (line 86), "audit architecture" (line 188), "the seven-step Inspect Scout pipeline is a published methodology the capstone could explicitly inherit or contrast with" (line 210). "Shape" appears ~14 times. Some are precise (referring to a literal pattern); others are vague. Audit and replace the vague ones with "design," "pattern," or the specific noun.

### B4.5 §7 "the plan's bet is that prose persistence plus LLM re-weighting beats structured-field maintenance" is good but undermined by "informally" three lines earlier

Line 230 says priority signals "persist informally in the work-log." Line 232–233 says the bet is "prose persistence plus LLM re-weighting beats structured-field maintenance." "Informally" pre-emptively concedes the bet. Replace "informally" with the operational description: "priority signals persist in the work-log as written notes that the next tick's prompt picks up; there is no structured field."

### B4.6 Deadwood

- Line 41 "Sections cite the relevant PR ids from the plan so the reader can move between review and plan without losing place." Functional metadata — cut, or move to a header note.
- Line 56 "Rather than tabulate every property of each benchmark, the differentiating story is two-dimensional." "Rather than" framing is throat-clearing; cut to "The differentiating story is two-dimensional:".
- Line 264 "Whether 'durable' earns the stronger framing of 'compounding' depends on measurements the plan does not yet collect." Cut "Whether…earns the stronger framing of"; rewrite as "'Compounding' is not yet a defensible claim — it depends on measurements the plan does not yet collect."

### B4.7 Italics density

§6.3 alone has ~10 italicized terms (*alignment auditing*, *eval-awareness*, *realism win rate*, *durable*, *intrinsic*, *spontaneously*). The italics-for-emphasis convention is overrun. Reserve italics for new-term-being-defined; cut emphasis-italics elsewhere.

### B4.8 §6's "the plan most depends on still-actively-shipping prior work" (line 172)

"Still-actively-shipping" is a fresh-from-Slack phrasing. Replace with "the prior work in §6 is the most actively evolving among the sections — three of the §6.3 precedents shipped in the four months before this review was written, and the precedent set may shift between drafts."

---

## Citation Graph Walk (Step 5)

### Seeds chosen (7, on the load-bearing axes for this artifact)

1. **SWE-Bench / Jimenez 2024** (ICLR 2024) — §1 anchor.
2. **OpenHands / Wang 2024** (ICLR 2025) — §2 anchor, closest match to multi-watcher shape.
3. **Reflexion / Shinn 2023** (NeurIPS 2023) — §5 anchor for episodic memory.
4. **SWT-Bench / Mündler 2024** — §3.1 anchor for proactive test generation.
5. **AuditBench / Anthropic 2026** — §6 anchor for verdict-aggregation.
6. **Inspect Scout / AISI 2026** — §6 anchor for transcript-walk methodology.
7. **ImpossibleBench / Zhong 2025** — §6 anchor for cheating measurement.

### Walk method

Each seed: Google Scholar "cited by" filter to last 12 months (2025-05 to 2026-05), plus search-beyond-arXiv on Anthropic Alignment Science, AISI blog, transluce.org, NIST CAISI. Time budget: ~5 minutes per seed.

### Findings per seed

**Seed 1 — SWE-Bench:**
- *Found and missed by lit review:* **SWE-CI** (Chen et al., arXiv:2603.03823, 2026-03). The single most important miss this cycle. See B1.1.
- *Found and missed:* **SWE-Bench Pro arXiv paper** (2509.16941, v2 2025-11) — only the Scale blog is cited. See B1.3.

**Seed 2 — OpenHands:**
- *Found and missed:* **RepairAgent** (Bouzenia et al., ICSE 2025, arXiv:2403.17134). Direct peer for §4 / `pr-30588a7`. See B1.2.
- *Found:* OpenHands SDK paper is cited (arXiv:2511.03690) — verified.

**Seed 3 — Reflexion:**
- *No new misses.* The Persona Vectors and Pan 2024 / Skalse / Pan 2022 chain is well-covered. Lightman 2023 and Cobbe 2021 verifier-guided generation are cited.

**Seed 4 — SWT-Bench:**
- *Found and cited:* Issue2Test, SWE-Tester, Otter / e-Otter++, TestExplora are all cited — good prior-cycle coverage.
- *No new misses on the proactive-test-generation axis.*

**Seed 5 — AuditBench:**
- *Found and missed:* **Introspection Adapters** (alignment.anthropic.com, 2026) and **A3: Automated Alignment Agent** (alignment.anthropic.com, 2026). Both supersede AuditBench's auditing-tool results. See B1.5.

**Seed 6 — Inspect Scout:**
- *No new misses.* The lit review covers the AISI 2025 CTF case study, the 2026 pipeline blog, and the PyPI release.

**Seed 7 — ImpossibleBench:**
- *Found and missed:* **Reward Hacking Benchmark (RHB)** (Thaman, arXiv:2605.02964, 2026-05-03) — the most recent peer. Frontier exploit rates 0–13.9% on tool-use shortcut tasks.
- *Found and missed:* **Benchmarking Reward Hack Detection in Code Environments via Contrastive Analysis** (arXiv:2601.20103, 2026-01) — the *detection* counterpart, directly relevant to §6.3's "audit sensitivity is open question" framing.

### Coverage assessment

Walk found 6 new prior-art entries not in the lit review or prior cycles:
1. SWE-CI (B1.1) — most damaging miss
2. RepairAgent (B1.2)
3. SWE-Bench Pro arxiv paper (B1.3)
4. RHB (B1.4)
5. Reward Hack Detection contrastive paper (B1.4)
6. Introspection Adapters + A3 (B1.5)

This is more new prior art than Cycle 5 found (which surfaced Issue2Test / SWE-Tester / TestExplora). Cycle 6 is not converging — the citation-graph yield went up rather than down. The dominant cause is publication-time: SWE-CI (March 2026), RHB (May 2026), and Reward Hack Detection (January 2026) all post-date the previous walk's date filter. The lit review needs another walk before any further structural edits.

---

## Summary Table

| # | Section | Severity | Category |
|---|---------|----------|----------|
| B1.1 | §7 | SUBSTANTIVE | Missed prior art (SWE-CI — load-bearing) |
| B1.2 | §4 | SUBSTANTIVE | Missed prior art (RepairAgent) |
| B1.3 | §1 | SUBSTANTIVE | Missing paper for cited benchmark (SWE-Bench Pro) |
| B1.4 | §6 | SUBSTANTIVE | Missed prior art (RHB, Reward Hack Detection) |
| B1.5 | §6 | SUBSTANTIVE | Missed prior art (Introspection Adapters, A3) |
| B1.6 | §5/Conclusion | SUBSTANTIVE | "Compounding" still under-specified after 6 cycles |
| B1.7 | §1 | SUBSTANTIVE | Matrix asymmetry with ProgramBench caveat |
| B1.8 | Conclusion | PHRASING | Bothsidesist contribution sentence |
| B2.1 | §6.3 | SUBSTANTIVE | Subsection too long; split into §6.3 / §6.4 |
| B2.2 | Intro | SUBSTANTIVE | Filler terms-paragraph; cut |
| B2.3 | §3.2 | PHRASING | Awkward orphan subsection |
| B2.4 | Conclusion | PHRASING | Repeats §6 |
| B3.1 | Appendix | SUBSTANTIVE | "Auto-sequence" gloss circular |
| B3.2 | §1 | SUBSTANTIVE | "Execute-only permissions on binary" undefined |
| B3.3 | §6 | SUBSTANTIVE | "CTF" undefined |
| B3.4 | §6 | SUBSTANTIVE | "Allowlist" needs §6 re-anchor |
| B3.5 | §3.1 | SUBSTANTIVE | "Fail-to-pass rate" needs gloss |
| B3.6 | §5 | SUBSTANTIVE | "Process supervision" gloss assumes MATH context |
| B3.7 | §5 | SUBSTANTIVE | "Activation space / probe directly" undefined |
| B3.8 | §6.2 | SUBSTANTIVE | Five-clause sentence → bullet list |
| B3.9 | §6.3 | PHRASING | "Eval-aware sabotage" not glossed |
| B3.10 | §4 | PHRASING | "APR" acronym overhead |
| B4.1 | Intro | PHRASING | Diagram + redescription paragraph duplication |
| B4.2 | §1 | SUBSTANTIVE | 250-word paragraph; split |
| B4.3 | various | PHRASING | "Structurally" overuse (5x) |
| B4.4 | various | PHRASING | "Shape" overuse (~14x) |
| B4.5 | §7 | PHRASING | "Informally" undermines later claim |
| B4.6 | various | PHRASING | Deadwood (lines 41, 56, 264) |
| B4.7 | §6.3 | PHRASING | Italics density |
| B4.8 | §6 | PHRASING | "Still-actively-shipping" slang |

**Totals: 30 findings. 16 substantive, 14 phrasing.** Substantive findings dominated by Block 1 (8 substantive) and Block 3 (8 substantive). Block 4 mostly phrasing, as expected.

---

## What Prior Cycles Missed (cross-reference appendix)

I scanned `REVIEW_CYCLE_4_REGRESSION.md`, `REVIEW_CYCLE_5_REGRESSION.md`, and `CITATION_GRAPH_WALK_REGRESSION.md` after drafting the review above.

**Prior cycles' coverage of substantive findings:**
- Cycles 4 & 5 found and integrated: Issue2Test, SWE-Tester, Otter / e-Otter++, TestExplora, AuditBench, Inspect Scout, Meerkat, ImpossibleBench, overt-saboteur, coding-audit-realism, Petri 2.0. Good coverage on these axes.
- Cycle 5 raised "OpenAI Verified deprecation overstated as 'formal end'" and the lit review now reflects that.
- Cycle 4 raised Persona Vectors — integrated.

**What prior cycles missed that this cycle found:**
1. **SWE-CI** (March 2026) — the citation-graph-walk seed cluster around Dependabot/Renovate and §7's "sparsely populated quadrant" should have surfaced this. The walk reportedly found "no academic peers for the continuous-loop quadrant." That conclusion was already stale by Cycle 5 (CITATION_GRAPH_WALK_REGRESSION.md is dated 2026-05-15 but does not include SWE-CI). Either Scholar's date filter was set wrong or the seed list did not include "continuous integration agent benchmark."
2. **RepairAgent** (ICSE 2025) — should have been in Cycle 4's seed list as the canonical LLM-agent program-repair paper. It is older than most of the recent-misses, so this is a "didn't look in 2024–2025 ICSE" gap rather than a date-filter gap.
3. **RHB and Reward Hack Detection contrastive** — both January and May 2026; the walk's date-filter should have caught them but didn't. Likely cause: seeds did not include "reward hacking benchmark" as a search string. Add it to the seed list.
4. **Introspection Adapters / A3** — both on alignment.anthropic.com after Cycle 5's walk completed. Reasonable miss given timing, but flagged here for the next walk to include.

**Convergence signal:** The lit review has *not* converged. Cycle 5 found 4 substantive prior-art misses (Issue2Test cluster, etc.); Cycle 6 found 6. Findings are increasing, not decreasing. The methodology says three cycles is typical; this is now six and prior-art yield is still nontrivial. Recommendation: one more walk-focused cycle after these are integrated, then stop unless yield drops below 2 substantive misses.

**Next step:** integrate B1.1 (SWE-CI) first — it's the most damaging miss and shifts §7's framing. B1.2, B1.4, B1.5 cluster into a single "update §4 and §6 with the 2025-2026 peer-reviewed and Anthropic-blog precedents." B1.6 — close the compounding question with one falsifiable prediction or drop the framing.
