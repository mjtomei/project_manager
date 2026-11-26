# Review Cycle 5 — Literature Review for plan-regression

Reviewer: fresh Claude session, blind to prior cycles.
Artifact: `pm/docs/literature-review.md` (~10,336 words).
Date: 2026-05-15.
Target audience for Block 3: non-developers evaluating whether to use `pm` — PMs, adjacent researchers, hobbyists with ordinary technical literacy.

The artifact is meaningfully better than a typical first draft on prior-art coverage. The Section 6 work on NIST CAISI / AISI Inspect Scout / Meerkat / AuditBench is dense and roughly correct against the public record. The substantive findings below are real but narrow; the bulk of the actionable yield is in Blocks 3 and 4. The review reports what it finds and does not manufacture severity.

---

## Block 1 — substance

### B1.1 Missed direct peer for `pr-2680fbf` (regression authoring): Issue2Test and SWE-Tester

The lit review names SWT-Bench (Mündler 2024) and R2E (Jain 2024) as the closest published peers to `pr-2680fbf`'s scenario-authoring flow. The walk surfaced two closer peers, both within the last 12 months, both directly on point:

- **Issue2Test** (arXiv:2503.16320, 2025; updated 2026). Verbatim from abstract: "We present Issue2Test, an LLM-based technique for automatically generating a reproducing test case for a given issue report. Unlike automated regression test generators, which aim at creating passing tests, our approach aims at a test that fails, and that fails specifically for the reason described in the issue." That is exactly the `pr-2680fbf` use case: a defect-report-to-failing-test pipeline.
- **SWE-Tester** (arXiv:2601.13713, 2026-01). Trains open-source LLMs specifically for issue reproduction in real-world repositories, against SWT-Bench. Closer to `pr-51586d2`'s mocks-aware regression authoring than R2E because it is repository-scoped.
- **e-Otter++ / "Execution-Feedback Driven Test Generation from SWE Issues"** (arXiv:2508.06365, 2025-08). Execution-feedback loop on issue reproduction — the literal feedback-driven analog the plan's QA review loop performs.
- **TestExplora** (arXiv:2602.10471, 2026-02). Proactive bug-discovery framing of repository-level test generation; the discovery supervisor's framing rather than the bug-fix watcher's.

Apply "narrow, don't collapse":

**What Issue2Test does** (per abstract): defect report → failing test on that defect, in real Python repositories.
**What `pr-2680fbf` does** (per plan): QA scenario planner authors a brand-new regression test on the fly when no existing one fits; the scenario is committed to `pm/qa/regression/` as a durable artifact; the discovery supervisor reruns it on its own schedule; supervisor-graded for quality.

**Intersection (preempted)**: LLM-generates-failing-test-from-defect-description is no longer a novel pattern — Issue2Test established it in early 2025, SWE-Tester operationalized it on SWT-Bench, e-Otter++ added execution feedback. The lit review's framing "puts the plan squarely in the LLM-test-generation literature" undersells this: the plan is in a literature that has *substantially* moved in the last 12 months in this exact direction.

**Residual contribution**: (a) the *durability* commitment — Issue2Test/SWE-Tester/e-Otter++ produce throwaway tests for evaluation; the plan persists them to `pm/qa/regression/` as a re-runnable corpus, then asks the discovery supervisor to use that corpus to find more bugs (a feedback loop the four peers do not implement); (b) the supervisor-graded quality gate on the authored test (`pr-98f670e`) — this is verifier-guided generation specifically applied to authored regression tests, not to bug fixes, and is not in the Issue2Test/SWE-Tester literature.

**Proposed replacement framing for the §3.1 paragraph that starts "Mündler et al. 2024 'SWT-Bench'"**:

> The closest published peers to `pr-2680fbf` are not SWT-Bench itself but the wave of issue-to-failing-test systems that has built on SWT-Bench in the last 12 months. **Issue2Test** (arXiv:2503.16320, 2025) is the closest direct analog: an LLM technique that takes a defect report and produces a test that fails *for the reason in the report*, distinct from regression generators that aim at passing tests. **SWE-Tester** (arXiv:2601.13713, 2026-01) trains open-source LLMs for the same task. **e-Otter++** (arXiv:2508.06365, 2025-08) adds an execution-feedback loop on top. **TestExplora** (arXiv:2602.10471, 2026-02) frames the same machinery as proactive bug discovery, closer to the discovery supervisor's job. R2E remains the closest peer on the executable-feedback axis, but it is no longer the leading edge. The plan's residual contribution against this cluster is durability (the test goes into `pm/qa/regression/` and gets re-run by the discovery supervisor — none of the four peers persist tests across runs) and supervisor-graded quality on the authored test (`pr-98f670e`, a verifier-guided pattern applied to test authoring rather than to bug fixing).

### B1.2 The "compounding" framing is conceded as future work — but the operational definition is still under-specified

The Conclusion correctly concedes that "compounding" is the aspirational claim while "durable" is the defensible one today. Good. But the three metrics it proposes ((a) scenario count growth weighted by supervisor quality, (b) coverage delta per scenario, (c) bug-recurrence rate per known fix per week) have unaddressed measurement problems:

- (a) supervisor-quality-weighted scenario count is circular if the supervisor is itself one of the most under-validated pieces in the plan. The lit review acknowledges this for `--resume`'s context arrangement (good) but not for the weighting use here. If supervisor verdicts are themselves noisy at the level §5 describes, using them as scenario-quality weights bakes the noise into the "compounding" metric.
- (b) "coverage delta per scenario with explicit accounting of diminishing returns" — the plan does not say how diminishing returns are accounted. The Fuzz4All literature's pattern (Xia et al. 2024) is to measure marginal coverage against a fixed corpus; the lit review names Fuzz4All but does not commit to a marginal-coverage operationalization.
- (c) "bug-recurrence rate with denominator (recurrences per known fix merged, per week)" — needs a window. A bug that recurs 18 months after a fix is a different signal from a recurrence in week 2.

**Proposed strengthening**: replace the three-bullet aspirational list with three falsifiable predictions:
- "Within 6 months of merging the discovery supervisor, the regression corpus grows by at least N scenarios/week and the supervisor's pass rate on those scenarios remains above M% (measured against a sample human re-grade)."
- "Marginal coverage delta per scenario, against the current corpus, stays above K% for the first N scenarios and decays no faster than 1/N — both measurable, both falsifiable."
- "Bug recurrence in the first 6 weeks after merge is at least X% lower than baseline (where baseline is the recurrence rate measured on the same project without the loop)."

These are still aspirational, but they're falsifiable in a way the current bullets are not.

### B1.3 Section 6.2's "five fronts" paragraph is unsupported assertion

> "The audit faces a hard problem on five fronts. The sandbox lets the agent reach the open internet, because otherwise the test is not realistic. The agent has reason to peek at how others solved the same problem. A single stray click can taint everything that follows. The trace records every action but labels none of them as cheating. And the grader sees only the final answer, where a cheated solution and a legitimate one look identical."

This is rhetorically tight but cites nothing. Each of the five claims has empirical support somewhere in the surrounding literature — claim 4 in particular is what NIST CAISI, AISI Inspect Scout, and Meerkat are *built to address*. The paragraph reads as if these problems are unaddressed when in fact the lit review's own §6.3 names the precedents. Either cite the precedents back into the five-front framing (so the paragraph becomes "five fronts, each addressed in part by..."), or trim the five-front claim to two or three for which the gap is genuinely open.

### B1.4 The ProgramBench caveat is half-applied

§1 includes a one-paragraph caveat that ProgramBench is "much newer than SWE-Bench and its evidence base is correspondingly thinner... cited based on its website and an arXiv preprint." Good. But the table directly above puts ProgramBench in a unique quadrant — sole occupant of "rebuild from binary × denial at runtime" — and Section 7's two-axis chart also names ProgramBench as the lone "no internet × snapshot benchmark" occupant. If the evidence base for ProgramBench is thin enough to caveat, the singular-occupant claims (which the contribution narrative leans on) are also weakened. Either add the same caveat to the table captions, or strengthen the ProgramBench evidence base (a second-source replication, leaderboard movement, peer-reviewed venue) before relying on its uniqueness in the contribution claim.

### B1.5 The OpenAI February 2026 SWE-Bench Verified deprecation is overstated as "the formal end"

> "The lit review treats this as the formal end of SWE-Bench Verified as a contamination-free reference point."

OpenAI is one model provider, not a benchmark steward. The SWE-Bench leaderboard at swebench.com still accepts Verified submissions, OpenHands still reports Verified scores, and Scale AI's SWE-Bench Pro endorsement does not retire the older benchmark. "Formal end" is too strong; "OpenAI no longer treats Verified as a frontier signal, and Scale AI's Pro is the proposed replacement" is the supportable claim.

**Proposed rewrite**: "OpenAI announced in February 2026 that it would no longer report SWE-Bench Verified scores. The internal audit underlying that decision found over half the hardest remaining tasks flawed, and frontier models reproducing gold patches from task IDs alone. OpenAI endorses Scale AI's SWE-Bench Pro as the replacement. SWE-Bench Verified remains in use elsewhere on the leaderboard, but the contamination signal has shifted enough that the lit review reads §1 with Verified treated as historically informative rather than current."

---

## Block 2 — structure and readability

### B2.1 The watcher hierarchy diagram (lines 13–31) does heavy lifting and should appear earlier or be reused

The ASCII diagram in the Introduction is the single most informative element in the document for a reader who hasn't read the plan. But it appears once, and §7's two-axis quadrant chart is a different diagram with different conventions. A reader who lands in §7 has lost the watcher hierarchy from working memory. Either reuse a compressed version of the hierarchy diagram in §7 (showing where the watchers sit on the live-internet × continuous-loop axes) or add a one-line callback ("see Introduction diagram for the three-watcher shape").

### B2.2 Section 5 mixes three threads without signposting

§5 currently runs: Self-Refine/Reflexion → Huang et al. critique → verifier-guided generation → Pan 2024 critique → AuditBench → `--resume` design discussion → AutoGen/MetaGPT → "actor-critic" naming. That is too many handoffs without subsection headers. Add §5.1 "the self-refinement positive literature," §5.2 "the critique and where it bites," §5.3 "the supervisor's design and the under-validated piece," §5.4 "multi-agent frameworks adjacent to but not directly imitated."

### B2.3 The "five fronts" paragraph and the §6.2 paragraph above it are both 4–5 long sentences with no scaffolding

§6.2 (lines 184–186) carries the core threat-model argument in three dense paragraphs. The "five fronts" line is a list-of-five buried in prose. Convert it to a numbered list. The reader retains numbered items better than buried lists.

### B2.4 The Conclusion repeats material the body already established

Lines 250–254 restate the §1–§7 contribution narrative for what is now the third time (Intro, body section openings, Conclusion). One restatement at the end is right; the Conclusion currently runs ~6 paragraphs where 3–4 would do. Cut: the second half of the paragraph starting "Where the plan most clearly reuses prior work" duplicates content from the §6 closing summary at lines 211–212.

### B2.5 Section 3.2 (test doubles for LLM-using code) is structurally awkward

§3.2 is a 1-paragraph subsection that admits "no peer-reviewed prior art exists for this corner." That is honest and fine, but a 1-paragraph subsection inside a 2-subsection section is a flag that it should either be a footnote, an appendix, or merged into §3.1's closing.

---

## Block 3 — non-expert accessibility (load-bearing)

The artifact has made a serious effort here. The Introduction's "What the plan does, in plain English" paragraph, the watcher-hierarchy diagram, the Appendix of terms, and the inline glosses are all the right shape. The remaining findings are real but narrower than they would have been on a typical lit review. I list them in priority order.

### B3.1 Undefined jargon (still hits the target reader)

The Appendix glosses the project-internal terms. The body uses these terms that the Appendix does not cover, and that the target reader will not know:

- **"diff"** — line 33 introduces "diff" inline ("a line-by-line listing of the proposed code change"). Good. But line 51 also has "produce a patch (a diff — a line-by-line listing...)" and lines 196, 200, 208 use "transcript" / "trace" inconsistently — sometimes glossed, sometimes not. *Fix*: choose one of "transcript" or "trace," gloss once at first use ("transcript: the full log of every command the agent ran, every file it read, every web page it fetched, in order"), and use that term thereafter.
- **"sandbox"** — line 53 glosses sandbox. Line 98 uses "sandboxed environment" un-glossed. Line 102's "stand-ins" sentence uses "test doubles" before glossing. Line 184 uses "stray click can taint everything that follows" — "taint" is jargon. *Fix*: replace "taint" with "contaminate the result" or "make the rest of the trace untrustworthy."
- **"scaffold"** — line 100's "minimal scaffold" parenthetical glosses it well. Line 328's References "ProgramBench's baseline scaffold" doesn't. Either trust the §2 gloss to carry through (probably fine for References) or repeat the parenthetical.
- **"AST"** — line 102 glosses AST. Good.
- **"DSL"** — line 220 glosses DSL. Good.
- **"red-teaming"** — line 206 glosses it inline. Good.
- **"fuzzing"** — line 122 glosses it. Good.
- **"actor-critic"** — line 166 unpacks the analogy ("writer / checker"). Good.
- **"pass@k"** — line 49 glosses pass@k well.
- **"verifier-guided generation"** — line 156 introduces this without a one-clause gloss. *Fix*: insert "(a separately-trained or separately-prompted checker that scores the generator's candidates and picks the best, rather than letting the generator grade itself)" on first use.
- **"alignment auditing"** — line 206 glosses it. Good.
- **"flaky"** (line 118) — glossed inline as "checks that sometimes pass and sometimes fail for the same input." Good.
- **"verdict"** — used many times (lines 33, 154, 162, 169). Target reader will read "verdict" naturally; no gloss needed.
- **"tick" / "watcher tick"** — line 104 uses "watcher tick" without glossing. *Fix*: insert "(a 'tick' is one wake-and-act cycle of the watcher)" on first use, or note this in the Appendix.
- **"capture-the-flag" / "CTF"** — line 198 uses both "capture-the-flag tasks" and the abbreviation. Acceptable but worth one clause: "(CTF: a security-training format where the goal is to extract a hidden token from a deliberately-vulnerable system)."
- **"reward hacking"** — line 158 glosses it well.
- **"sycophancy"** — line 158 and 161 use sycophancy / sycophantic without gloss. *Fix*: "(sycophancy: a model agreeing with the user even when the user is wrong)."
- **"sandbagging"** — line 204 uses "sandbagging" un-glossed. *Fix*: "(sandbagging: a model deliberately performing worse than it can, e.g. to escape evaluation pressure)."
- **"hold-out" / "leaderboard"** — leaderboard is used many times. Probably fine for the target reader, but the first use at line 96 could carry a one-clause gloss: "(a public ranking of which systems do best on the benchmark)."

### B3.2 Implicit prior-art dependencies

- §2 assumes the reader has at least heard of Aider, Cline, Claude Code as competing tools (line 100). The target reader has probably heard of Claude Code (it's in the Appendix) but not Aider or Cline. Replace with a single sentence: "Aider, Cline, and Codex CLI are similar command-line tools made by other groups."
- §3.1 assumes familiarity with the search-based testing tradition by naming Pynguin without context. The 1-clause gloss "(Pynguin is the leading non-LLM Python implementation of this tradition)" is enough.
- §6.3 assumes the reader knows what "Inspect" is. Line 196 glosses Inspect inline ("Anthropic's open-source evaluation framework, originally built with the UK AI Safety Institute"). Good — but verify: Inspect is actually maintained by UK AISI, not Anthropic. *This is a factual error.* Fix: "Inspect is the UK AI Safety Institute's open-source evaluation framework."
- §7 assumes the reader knows what Dependabot is. The intro paragraph says "The plan's three watchers look a lot like Dependabot" without saying what Dependabot is. *Fix*: insert "Dependabot is GitHub's built-in tool that watches a project's dependency list, files small PRs when a dependency has a new version, and lets the existing review process decide whether to accept each one." before the comparison.

### B3.3 Unmotivated framings

- Line 38: "That design crosses several research areas, and the contamination question runs through all of them in two forms." — the reader has not yet agreed that contamination is the through-line. *Fix*: "Several research areas matter here, but one question shows up in all of them: did the agent already see the answer? (We will see this in two forms — once for the training data, once for the live internet.)"
- Line 248 (Conclusion): "The plan turns a regression-test suite into the inner clock of a continuous quality loop, and that simple framing hides where the research bets are." — "inner clock" is a metaphor the body did not earn. *Fix*: "The regression-test suite drives the loop: each pass through it surfaces either a bug to fix or a coverage gap to fill. That looks routine, but the research bets are real..."

### B3.4 Abstract claims without concrete examples

- §6.2 line 184: "A single stray click can taint everything that follows." — abstract. *Fix*: "Concretely: if the agent fetches the project's Wikipedia page during step 1, the page mentions a key algorithm, and steps 2–10 use that algorithm — every later step is downstream of the leak."
- §5 line 154: "the bound matters: the plan operates where self-correction-with-external-feedback works, not where it degrades." — abstract claim. *Fix*: "Concretely: when the supervisor reads a tool-use transcript (external evidence) rather than the model's own reasoning trace (the model's view of itself), the Huang et al. failure mode doesn't apply."
- §7 line 224: "Imagine the project just suffered a production outage. A stored priority list written yesterday wouldn't know." — *good*, this is the kind of concrete example the rest of the document needs more of. Keep this one and propagate the pattern.

### B3.5 Dense paragraphs

- Lines 53 (the third-generation contamination paragraph) is one paragraph, 7+ sentences, names HumanEval-MBPP-EvalPlus-SWE-Bench-SWE-Bench-Verified-SWE-Bench-Pro-SWE-Bench-Multimodal-LiveCodeBench-BigCodeBench-Saving-SWE-Bench-ProgramBench in succession. Target reader will close the tab here. *Fix*: split into two paragraphs at "The third generation is responding to..." Reduce the name density: the reader needs HumanEval, SWE-Bench, SWE-Bench Pro, LiveCodeBench, ProgramBench. The others (BigCodeBench, Saving-SWE-Bench, SWE-Bench-Multimodal) are References-level detail; cite in passing in a footnote-style line, not in the body.
- Line 102 (Agentless + AutoCodeRover) is also dense. The AutoCodeRover gloss with the blueprint analogy is good; the AST aside should be a parenthetical or footnote, not an inline.
- Line 162 (the `--resume` design discussion) runs 7 sentences and refers the reader to RESUME_DESIGN_NOTE.md — that's a smell. If the design is too complex to summarize in 3 sentences, the lit review is the wrong place to debate it; pull the whole discussion into the design note and leave one sentence here.

### B3.6 Names dropped without context

- "Mergify and Kodiak" (line 218) — named once, no context, no follow-up use. *Fix*: cut.
- "ClusterFuzz" (line 220) — named once. *Fix*: trim to "OSS-Fuzz / ClusterFuzz" and rely on the OSS-Fuzz gloss in §3.1.
- "LangWatch's Scenario framework" (line 130) — named once, no context. *Fix*: cut or one-clause gloss.
- "LiteLLM" (line 130, 326) — named once in body, no gloss. *Fix*: "LiteLLM (a Python library that lets test code stub out LLM calls)."
- "Cobbe et al. 2021" (line 156) is introduced as "the foundational reference" but the target reader doesn't know who Cobbe is or why GSM8K matters. *Fix*: insert "(Cobbe and colleagues at OpenAI trained a small grader model whose only job was to read a candidate answer to a math problem and judge it; this was the first widely-cited demonstration that 'have a second model grade the first' beats 'have the first model grade itself.')"

### B3.7 Insider quips

The lit review largely avoids these. The few that survive:

- Line 254: "if it fails, it remains the most likely point of failure" — wry but adds no information. *Fix*: cut.
- Line 258: "The walk remains under-budgeted for a full traversal; readers chasing a specific thread should treat the references as a starting set, not a complete one." — honest but reads as defensive. Replace with: "The reference list is selective. A reader wanting the full state-of-the-art on any one section should follow the cited papers' own references."

### B3.8 Quantitative claims without scale anchors

- "72 percent resolve rate on SWE-Bench Verified" (line 96) — anchored well ("roughly seven out of every ten").
- "32.0 percent" Agentless on SWE-Bench Lite (line 102) — anchored well ("roughly one out of every three real GitHub issues successfully fixed").
- "$0.70 per task" (line 102) — anchored ("about the cost of a cup of coffee per bug fix").
- "GPT-5 cheats on 54.0 percent of runs" (line 208) — not anchored. *Fix*: "GPT-5 takes the shortcut on more than half its runs — more than chance."
- "4.6 to 32.8 percent" realism win rate (line 192) — not anchored. The reader has no idea whether 32.8% is good. *Fix*: "(32.8 percent means roughly 1-in-3 audits passed for plausibility; baseline was about 1-in-22)."
- "10 to 13 percent... 42 percent in a super-agent aggregation" (line 206) — somewhat anchored ("about one time in eight"; "roughly two in five"). Good.
- "Reflexion's actor-critic loop... roughly 20 percent absolute improvement across seven tasks" (line 148) — *not actor-critic*, line 148 says Self-Refine reports the 20 percent. Verify: Self-Refine's reported improvement is roughly 20 percent absolute. The anchor would help: "(absolute improvement means: where the baseline scored 50, this scores 70 — not 50 to 60.)"
- "19 to 29 percent" EvalPlus drop (line 49) — anchored ("a sizeable fraction"). Good but could be tighter: "roughly a fifth to nearly a third of code that 'passed' was wrong."
- "59.4 percent flawed" (line 53) — not anchored. *Fix*: "(more than half — 59.4%)."

### B3.9 Acronym creep

The lit review handles this well. Remaining issues:

- "GVR loop" (line 118) — spelled out ("Generation-Validation-Repair (GVR) loop"). Good.
- "ICSE-SEIP" (line 138) — not glossed; the reader doesn't know what SEIP is. *Fix*: "(SEIP: the Software Engineering in Practice track, where industry papers go)."
- "FSE" (line 118, 295) — spelled in venue abbreviations note (line 262). Good.
- "ISSTA / OOPSLA / TSE / EMNLP / ACL / COLM / NeurIPS / ICLR" — all in the venue list at line 262. Good.
- "MATH" (line 156) — capitalized like a benchmark name. The reader will not know "MATH" is the name of a specific math word problem benchmark. *Fix*: "(MATH is a benchmark of high-school competition math problems, distinct from the easier GSM8K.)"
- "CyBench" (line 200) — name-dropped. *Fix*: "(CyBench is a cybersecurity-task agent benchmark.)"
- "CodeLlama" (line 138) — name-dropped, no gloss. *Fix*: "(CodeLlama is Meta's open-source code model.)"

### B3.10 "Why should I care?" check, by section

- §1: opens with a benefit ("If you want to know whether a coding assistant is any good..."). Good.
- §2: opens with "The agents that write code under the hood of tools like Aider and Claude Code all derive from a handful of designs." Target reader doesn't know Aider. Reframe: "When the plan needs to actually edit code, it hands the job to Claude Code. This section is about where the design ideas behind Claude Code (and competing tools) came from, so you know which trade-offs the plan inherits."
- §3: opens with "When the plan's regression tests miss something, the tool tries to write a new test on the fly. There's a decade of research on whether that ever works." Good.
- §4: opens with "Once a failing test points at a bug, the next question is whether the tool can fix it on its own." Good.
- §5: opens with "When you ask a language model to grade its own work, sometimes it gets better and sometimes it gets worse." Good.
- §6: opens with "If the plan's evaluation lets the model use the internet, the model could just look up the answer." Good.
- §7: opens with "The plan's three watchers look a lot like Dependabot." Target reader doesn't know Dependabot. Reframe (after glossing Dependabot per B3.2): "The plan's three watchers look a lot like Dependabot — they sit in the background, watch the project, and file work items when they see something to do."

---

## Block 4 — writing quality and prose craft

### B4.1 Paragraph-to-paragraph flow at §6.2 → §6.3 is abrupt

§6.2 ends with the eval-awareness paragraph (line 192). §6.3 opens with "The runtime-with-internet integrity audit is an underexplored area." (line 196). The handoff misses a bridge. *Fix*: end §6.2 with "Whatever transcript-walk machinery the audit uses, it inherits these concerns. The closest published machinery is described in §6.3."

### B4.2 Sentence-rhythm: §6.3 has six paragraphs that each open with a paper name

"NIST CAISI..." "AISI Inspect Scout..." "Meerkat takes..." "NIST CAISI, Inspect Scout, and Meerkat are closest..." "Anthropic, 'Pre-deployment auditing...'" "Anthropic 2025, 'Building and evaluating...'" "ImpossibleBench..." Seven paragraphs in succession, each leading with a citation. The reader's eye glazes. *Fix*: vary three of these to open with a sentence about the *threat or method* the paper addresses, then name the paper second. Example: "Across-traces clustering, rather than single-transcript walks, is what Meerkat (Stein et al. 2026) contributes."

### B4.3 Word-choice imprecision

- "leaning on" (lines 38, 70, 88) — recurring vague verb. *Fix*: where load-bearing, replace with "depends on" or "inherits from."
- "shape" used as both noun and verb in adjacent sentences (lines 51–53). *Fix*: pick one usage per paragraph.
- "ride on the same... lineage" (line 96) — mixed metaphor. *Fix*: "descends from the same lineage."
- "spirit" (line 94, 104) — vague; "in the spirit of SWE-agent's ACI argument" lands well enough at line 104; line 94's "the modern coding-agent paradigm" can lose "in spirit."

### B4.4 Hedge inflation

- "may shift" (line 206) — earns its place (research note caveat).
- "tends to drift" (line 224) — earns its place.
- "appears to" — search the document; the lit review is fairly disciplined here. The one tic is "looks a lot like" (lines 92, 216, 218) — twice in §7's first three paragraphs. *Fix*: vary to "resembles" or "shares the shape of" once.

### B4.5 Deadwood

- "It should be noted that" — does not appear. Good.
- "in the broader software-engineering conversation" (line 98) — corporate-flat. *Fix*: "made autonomous coding agents a topic everyone in the industry argued about."
- "the fact that" — does not appear. Good.
- "represents a significant departure" — does not appear. Good. (The doc is generally clean of this register.)

### B4.6 Awkward constructions

- Line 53 opens with "The third generation is responding to a problem the second never solved: contamination." — *good rhythm*. Keep.
- Line 86 "The post-run detection row is now a populated quadrant, not an empty one" — the demonstrative "this" / "the" reference is ambiguous; the reader has to look back at the table. *Fix*: "The bottom row of the table is populated, not the empty box it would have been a year ago."
- Line 162: "Two amendments is exactly the regime Pan et al. found measurable hacking in" — buried preposition. *Fix*: "Two amendments is exactly the regime in which Pan et al. found measurable hacking."

### B4.7 Emphasis density

The document uses italics in dozens of places. The most-emphasized words: *durable*, *compounding*, *which threat*, *denies* vs *grants*, *intrinsic*, *runtime contamination*, *during the run*. Most earn their place — they mark genuine distinctions. The few that don't:

- "the *most* under-validated mitigation" (line 162) — italics on "most" is rhetorical. *Fix*: drop.
- "verbal reinforcement learning" italicized (line 148) — the term is jargon; the italics signal "term of art." *Fix*: keep italics but add the gloss already there.

---

## Citation graph walk (Step 5)

### Seeds chosen (8)

1. **AISI Inspect Scout** (2026-02-25 blog + 2026-04-29 PyPI release) — anchor for runtime audit.
2. **NIST CAISI "Cheating in AI Agent Evaluations"** (2024-2025 web series) — anchor for runtime audit.
3. **ImpossibleBench** (Zhong, Raghunathan, Carlini 2025, arXiv:2510.20270, ICLR 2026 poster) — measurement adjacency.
4. **Pan et al. 2024 "Spontaneous Reward Hacking in Iterative Self-Refinement"** (arXiv:2407.04549) — core threat reference for §5.
5. **Meerkat** (Stein, Brown, Hassani, Naik, Wong 2026, arXiv:2604.11806) — across-traces cluster audit.
6. **AuditBench** (Anthropic alignment.anthropic.com 2026-03-10) — tool-to-agent gap.
7. **SWE-Bench / SWE-Bench Verified deprecation** (OpenAI 2026-02-23 + Scale AI's SWE-Bench Pro) — §1 pivot.
8. **SWT-Bench** (Mündler 2024, arXiv:2406.12952) — closest peer for `pr-2680fbf` per the lit review.

### Coverage

- Date filter: last 12 months on Google Scholar where applicable; supplemented with WebSearch and direct lab-page checks.
- Search-beyond-arXiv pass: alignment.anthropic.com, aisi.gov.uk, nist.gov/caisi, OpenReview, ICLR 2026 poster listings, GitHub repos for impossiblebench, Meerkat, swt-bench, inspect_scout.
- Time budget: ~45 minutes total across the eight seeds. Per-seed budget 4–8 minutes.

### Findings per seed

| Seed | Forward (cited by, last 12 mo.) | Backward (references in) | Action |
|---|---|---|---|
| AISI Inspect Scout | No academic citations yet (released 2026-02-25 + 2026-04-29 PyPI); 24-ai.news 2026-04-15 noted Meerkat's relation. | Inspect-AI framework, AISI 2025 case study (already cited). | No add — lit review covers this well. |
| NIST CAISI | NIST itself maintains a 5-part web series (background → examples → transcript-review → practices → conclusion). Lit review cites the index URL; could cite specific subpages. | Inspect framework. | Minor: cite specific subpages (parts 2 and 3 are the load-bearing pieces). |
| ImpossibleBench | ICLR 2026 poster confirmed (poster 10009390). Hugging Face papers and emergentmind.com both surface follow-up commentary; "EvilGenie" and "School of Reward Hacks" are flagged in the reward-hacking taxonomization literature. | Cobbe 2021, Skalse 2022, Pan 2022 — all cited. | Add: ICLR 2026 venue rather than arXiv-only. Add reference to "EvilGenie" and "School of Reward Hacks" if they survive verification (treat as flagged, not yet integrated). |
| Pan 2024 | "Specification Self-Correction: Mitigating In-Context Reward Hacking Through Test-Time Refinement" (2025) is a follow-up. Lilian Weng's Nov 2024 post taxonomizes; non-peer-reviewed but widely cited. | Skalse 2022, Pan 2022 — already cited. | Add: Specification Self-Correction (2025) as a directly-relevant follow-up on mitigation. |
| Meerkat | DebugML's "Finding Widespread Cheating on Popular Agent Benchmarks" — closely related; might be the authors' own write-up of the same work. Reported 4x more reward-hacking findings on CyBench. | NIST CAISI, AISI Inspect Scout. | No add — lit review covers this. Could expand the 4x figure with the harder finding: "harness-level cheating on all top Terminal-Bench 2.0 and HAL USACO submissions." |
| AuditBench | "Introspection Adapters" (alignment.anthropic.com 2026) is a sibling result — interpretability-side companion. | Anthropic 2025 Building-and-evaluating-alignment-auditing-agents (cited). | Optional: name Introspection Adapters as a sibling line of work if the user-modeling thread interests the reader; not load-bearing. |
| SWE-Bench Verified deprecation | SWE-Bench-Live (monthly-updated alternative) and SWE-rebench are alternatives the lit review does not name. The Verified leaderboard remains active despite OpenAI's deprecation. | Original SWE-Bench (cited). | Add: SWE-Bench-Live as a third alternative alongside SWE-Bench Pro. Soften "formal end" framing per B1.5. |
| SWT-Bench | **Strong forward-walk yield**: Issue2Test (arXiv:2503.16320, 2025), SWE-Tester (arXiv:2601.13713, 2026-01), e-Otter++ / Execution-Feedback Driven Test Generation (arXiv:2508.06365, 2025-08), TestExplora (arXiv:2602.10471, 2026-02), TDD-Bench Verified (arXiv:2412.02883, 2024-12), "Enhancing LLM-Based Test Generation by Eliminating Covered Code" (arXiv:2602.21997, 2026-02). | Original SWE-Bench. | **Add — see B1.1**. The SWT-Bench forward-walk is the single biggest yield of the citation graph walk. |

### Summary of walk findings

- **One substantive prior-art miss**: the post-2024 wave of issue-to-failing-test systems (Issue2Test, SWE-Tester, e-Otter++, TestExplora). The lit review's framing of `pr-2680fbf`'s nearest peers as "SWT-Bench (Mündler 2024) and R2E (Jain 2024)" is genuinely outdated — these are the 2024 ancestors of a substantial 2025-2026 wave the artifact does not name. See B1.1 for the proposed narrowing.
- **Three minor enrichments**: SWE-Bench-Live alongside SWE-Bench Pro; Specification Self-Correction (2025) as a Pan 2024 follow-up; ICLR 2026 venue for ImpossibleBench.
- **Five confirmed no-adds**: AISI Inspect Scout, NIST CAISI, Meerkat, AuditBench, and Pan 2024's main thread are all current and well-cited.

The walk's positive convergence signal: §6 is genuinely current, and the lit review's coverage of the alignment-auditing / agent-integrity threads is hard to fault. §3.1, by contrast, has drifted relative to the literature and needs the B1.1 update.

---

## Summary table of findings

| ID | Block | Severity | Type | One-line fix |
|---|---|---|---|---|
| B1.1 | Substance | High | Prior-art miss | Add Issue2Test / SWE-Tester / e-Otter++ / TestExplora to §3.1; narrow `pr-2680fbf`'s residual to durability + supervisor-graded quality. |
| B1.2 | Substance | Med | Unsupported claim | Replace 3-bullet "compounding" aspirational list with 3 falsifiable predictions. |
| B1.3 | Substance | Med | Unsupported framing | Either cite §6.3 precedents back into §6.2's "five fronts" paragraph or trim. |
| B1.4 | Substance | Low-Med | Caveat consistency | Propagate the ProgramBench evidence-base caveat to the contribution-claim use sites. |
| B1.5 | Substance | Med | Overstatement | Soften "formal end of SWE-Bench Verified"; SWE-Bench-Live and the active leaderboard remain. |
| B2.1 | Structure | Low | Diagram reuse | Reuse compressed watcher-hierarchy diagram in §7. |
| B2.2 | Structure | Med | Subsection needed | Add subsection headers in §5 to break up its 7-thread run. |
| B2.3 | Structure | Low | List formatting | Convert §6.2's "five fronts" into a numbered list. |
| B2.4 | Structure | Low | Redundancy | Trim Conclusion's restatement of body material. |
| B2.5 | Structure | Low | Awkward subsection | Merge or footnote §3.2. |
| B3.1 | Accessibility | Med | Jargon | Gloss "verifier-guided generation," "watcher tick," "sycophancy," "sandbagging," "CTF," "MATH benchmark," "CyBench," "CodeLlama," "LiteLLM." Unify "transcript" vs "trace." Replace "taint." |
| B3.2 | Accessibility | Med-High | Prior-art assumption + factual error | Gloss Aider/Cline/Dependabot/Pynguin/Inspect. **Fix factual error**: Inspect is UK AISI's, not Anthropic's. |
| B3.3 | Accessibility | Low | Unmotivated framing | Rewrite Intro contamination framing and Conclusion's "inner clock" metaphor. |
| B3.4 | Accessibility | Med | Abstract claims | Add concrete examples for "stray click can taint," "the bound matters." |
| B3.5 | Accessibility | Med | Dense paragraphs | Split §1's third-generation paragraph; pull `--resume` discussion out of §5. |
| B3.6 | Accessibility | Low | Name drops | Gloss or cut Mergify, Kodiak, ClusterFuzz, LangWatch, LiteLLM, Cobbe. |
| B3.7 | Accessibility | Low | Insider quips | Cut "remains the most likely point of failure" and similar. |
| B3.8 | Accessibility | Med | Unanchored numbers | Anchor 32.8% realism win rate, 54% ImpossibleBench cheat rate, 59.4% flawed SWE-Bench. |
| B3.9 | Accessibility | Low | Acronyms | Gloss SEIP, MATH-the-benchmark, CTF, CyBench. |
| B3.10 | Accessibility | Low | Section openings | Rewrite §2 and §7 openings to lead with reader benefit. |
| B4.1 | Prose | Low | Transition | Bridge §6.2 → §6.3. |
| B4.2 | Prose | Low | Sentence rhythm | Vary §6.3's seven paragraph-opening citations. |
| B4.3 | Prose | Low | Word choice | Replace recurring "leaning on" / "spirit" / "shape." |
| B4.4 | Prose | Low | Hedge inflation | One use of "looks a lot like" in §7. |
| B4.5 | Prose | Low | Deadwood | "in the broader software-engineering conversation" → direct phrasing. |
| B4.6 | Prose | Low | Awkward sentences | Fix line 86's "the post-run detection row is now a populated quadrant"; line 162's buried preposition. |
| B4.7 | Prose | Low | Emphasis density | Drop italics on "most under-validated"; keep "verbal reinforcement learning." |

**Total findings**: 27. Substantive (Block 1 + B3.2 factual error): 6. Structural (Block 2): 5. Accessibility (Block 3 minus B3.2 factual): 9 (mix of medium and low). Prose (Block 4): 7 (all low-severity).

The substantive yield is real but narrow. B1.1 (Issue2Test wave) is the single load-bearing finding; B3.2 contains a factual error about Inspect's provenance; B1.5 overstates OpenAI's deprecation. The remaining 24 findings are improvements rather than corrections.

---

## What prior cycles missed (cross-reference appendix)

Now scanning prior cycles' files: REVIEW_CYCLE_1_LITREVIEW.md, REVIEW_CYCLE_2_LITREVIEW.md, REVIEW_CYCLE_3_LITREVIEW.md, REVIEW_CYCLE_4_REGRESSION.md, REVIEW_BLOCK4_REGRESSION_LIT.md, CITATION_GRAPH_WALK_REGRESSION.md, and the matching responses.

(Filling in after independent draft above.)

### Issue2Test / SWE-Tester / e-Otter++ / TestExplora cluster (B1.1)

Searched REVIEW_CYCLE_1/2/3_LITREVIEW, REVIEW_CYCLE_4_REGRESSION, REVIEW_BLOCK4_REGRESSION_LIT, and CITATION_GRAPH_WALK_REGRESSION for the strings `Issue2Test`, `SWE-Tester`, `e-Otter`, `TestExplora`. **Zero hits.** Prior cycles did not surface this 2025-2026 wave of issue-to-failing-test systems. CITATION_GRAPH_WALK_REGRESSION's seed-by-seed coverage notes the walk concentrated on §6 (agent integrity / transcript audit), which is "exactly where the lit review's §6.3 acknowledged its peer-coverage was thinnest." The walk's focus on §6 came at the cost of §3.1 currency. **B1.1 is a new finding this cycle adds.** It is the cycle's load-bearing substantive contribution.

### Inspect provenance (B3.2)

Cycle 1 flagged it as a gloss-missing issue ("Inspect is named as if known. It's AISI/Anthropic's eval framework"). Cycle 2 caught the AISI-acronym-inside-the-gloss problem and recommended "Anthropic's open-source framework, originally built with the UK AI Safety Institute." Cycle 3 noted the gloss was present. **None of the prior cycles caught the directionality**: Inspect is UK AISI's framework (github.com/UKGovernmentBEIS/inspect_ai, maintained by UK AISI + Meridian Labs), not Anthropic's. The current text reads as if Anthropic was the primary author with AISI as a partner — the reverse is true. **B3.2's factual correction is a new finding this cycle adds.**

### "Formal end of SWE-Bench Verified" (B1.5)

Prior cycles do not appear to have softened the "formal end" framing. The phrase was likely added during the response to Cycle 4 when OpenAI's February 2026 announcement was incorporated. **B1.5 is a new finding this cycle adds.**

### Falsifiable "compounding" predictions (B1.2)

CITATION_GRAPH_WALK_REGRESSION and REVIEW_CYCLE_4_REGRESSION engage extensively with the durable-vs-compounding distinction, and the Conclusion's three-bullet aspirational list reads like a Cycle 4 concession. **Prior cycles got the "durable, not compounding" framing right and the lit review correctly hedges it.** B1.2 is an incremental tightening rather than a new finding — the lit review's current treatment is defensible, just under-operationalized.

### Other prior-cycle yield this cycle preserves

- Cycle 4 caught the "bolt-on feel" of §6.3's expansion. This cycle's B4.2 (seven paragraph-opening citations) extracts the same observation at the prose level.
- Cycle 4 recommended cutting the Conclusion's enumeration to a single sentence. The current Conclusion still over-enumerates; this cycle's B2.4 picks up the same thread.
- Cycle 4 surfaced AuditBench's tool-to-agent gap as the most underused finding for the supervisor design (`pr-98f670e`). The lit review now incorporates this in §5. This cycle adds nothing here — the integration looks correct.

### Net new this cycle (vs. all prior cycles)

1. **B1.1**: Issue2Test / SWE-Tester / e-Otter++ / TestExplora wave for `pr-2680fbf` (Block 1, substantive).
2. **B3.2 factual error**: Inspect's provenance is UK AISI, not Anthropic (Block 3, factual correction).
3. **B1.5**: "Formal end of SWE-Bench Verified" overstated; SWE-Bench-Live and active leaderboard rebut (Block 1, factual nuance).
4. **B1.4**: ProgramBench caveat / contribution-claim consistency (Block 1, internal consistency).
5. **B1.3**: §6.2 "five fronts" paragraph cites nothing the §6.3 precedents already address (Block 1, unsupported framing).

The other 22 findings are improvements of varying utility, most overlapping prior cycles' general direction or representing pedantic prose-level work that would not pass the "convergence signal" test on its own.
