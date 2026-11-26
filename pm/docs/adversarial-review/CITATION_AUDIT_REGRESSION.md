# Citation Audit — Regression / Autonomous-Loop Literature Review

**Artifact audited:** `pm/docs/literature-review.md` (the autonomous regression and bug-fix loop literature review).

**Scope.** Full audit of every citation in §§2–6 across two tiers, per the updated `pm/docs/adversarial-review/CITATION_USE_AUDIT.md` protocol (which requires every citation to be audited and tier-labelled). Tier-1 entries (the first major section below, "Load-bearing citation set") were produced first; Tier-2 entries (the "Tier-2 supplemental pass" section at the end) were added later to cover the remaining citations. Format follows `CITATION_AUDIT_USERMODEL_EXTENSION.md`.

**Tiering note (per protocol step a).** Every entry below is tagged with an explicit `**Tier:**` line. The tiering criteria used:

- **Tier 1 — Deep audit.** Citations the argument materially depends on: those that preempt/anchor a novelty claim, supply a load-bearing empirical figure, anchor a methodological choice, or are invoked across multiple sections. Full abstract (+ key web sources where retrievable) read with the full per-citation entry (doc passage → source quote → verdict → proposed rewrite). The 27 citations under "Load-bearing citation set" are Tier 1.
- **Tier 2 — Light audit.** Citations that support but do not anchor the argument — background, "as also noted by", one-off references where the argument does not turn on the characterization. Abstract-level check only; brief per-citation entry (doc passage → abstract gloss → verdict). Proposed rewrites only when the issue is egregious. The Tier-2 supplemental pass at the end covers these.
- **Tier 3 — Reference-list-only.** Citations that appear in the reference list with no inline argumentative use. One-line entry sufficient.

**Method.** arXiv abstract/HTML fetches via WebFetch; web search where the primary URL 404'd; blog posts (Anthropic alignment notes, OpenAI posts, Playwright docs) fetched directly. Where only the abstract was retrievable, the verdict is flagged provisional and the abstract was the basis. Where the URL returned 404, the citation is in the "Fetch failures" section and the verdict is provisional.

**How to walk this.** Read top-to-bottom and apply or reject each proposed rewrite. Faithful entries can be skimmed. The summary table at the end ranks entries by required action.

---

## Load-bearing citation set

**Tier:** every entry in this section is **Tier 1** (deep audit). Tier-2 (supporting) and Tier-3 (ref-list-only) entries are in the "Tier-2 supplemental pass" section at the end of the document.

These are the citations the argument materially depends on.

**Benchmarks and contamination (§2, §5):**
- ProgramBench (arXiv:2605.03546) — anchors §2's "harness is the contribution" claim.
- SWE-Bench (Jimenez et al. 2024) — anchors the benchmark lineage; supporting.
- SWE-Bench Pro (Deng et al. 2025, [arXiv:2509.16941](https://arxiv.org/abs/2509.16941)).
- OpenAI 2026 SWE-Bench Verified retraction post.
- Saving SWE-Bench mutation (Garg et al. 2026, [arXiv:2510.08996](https://arxiv.org/abs/2510.08996)).
- EvalPlus (Liu et al. 2023) — supporting.

**Harness comparison (§3):**
- SWE-agent (Yang et al. 2024).
- Agentless (Xia et al. 2024, [arXiv:2407.01489](https://arxiv.org/abs/2407.01489)).
- OpenHands (Wang et al. 2024).

**QA / test generation (§4a):**
- Playwright Test Agents.
- TestExplora (arXiv:2602.10471).
- CodaMosa (Lemieux et al. 2023) — supporting; widely cited, abstract-level check.
- OSS-Fuzz (Serebryany 2017) — supporting; abstract-level check.

**Automated program repair (§4b):**
- RepairAgent (Bouzenia et al. 2025, [arXiv:2403.17134](https://arxiv.org/abs/2403.17134)).
- AutoCodeRover (Zhang et al. 2024).
- Self-Debug (Chen et al. 2023).
- GenProg / Sapfix — supporting; long-established literature.

**Verifier / self-correction (§4c):**
- Cobbe et al. 2021 (GSM8K verifier).
- Lightman et al. 2023 ("Let's Verify Step by Step").
- Huang et al. 2023 ("LLMs Cannot Self-Correct Reasoning Yet").
- Reflexion (Shinn et al. 2023).
- Pan et al. 2024 (Spontaneous Reward Hacking in Iterative Self-Refinement).
- AuditBench (Anthropic 2026).

**Audit / cheating detection (§4d):**
- Meerkat (Stein et al. 2026, [arXiv:2604.11806](https://arxiv.org/abs/2604.11806)).
- ImpossibleBench (Zhong et al. 2025, [arXiv:2510.20270](https://arxiv.org/abs/2510.20270)).
- RHB (Thaman 2026, [arXiv:2605.02964](https://arxiv.org/abs/2605.02964)).
- TRACE (Deshpande et al. 2026, [arXiv:2601.20103](https://arxiv.org/abs/2601.20103)).
- NIST CAISI / AISI Inspect Scout — supporting; blog-grade.

**Autonomous loops (§4e):**
- SWE-CI (Chen et al. 2026, [arXiv:2603.03823](https://arxiv.org/abs/2603.03823)).

**Harness-evolution adjacent work (§6):**
- Agentic Harness Engineering (arXiv:2604.25850).
- "The Last Harness You'll Ever Build" (arXiv:2604.21003).

The two most load-bearing are **ProgramBench** (anchors the whole §2 framing) and **Pan et al. 2024** (anchors the §4c reward-hacking caution that the plan's most under-validated component rests on). Both got the most careful read.

---

## I. Benchmarks and contamination (§2, §5)

### ProgramBench — [arXiv:2605.03546](https://arxiv.org/abs/2605.03546)

**Doc passage as currently written (§2):**
> ProgramBench (the 200-task benchmark where Claude Opus 4.7 with the minimal mini-swe-agent scaffold currently tops the leaderboard — programbench.com snapshot 2026-05-14; [arXiv:2605.03546](https://arxiv.org/abs/2605.03546)) gives the agent only a compiled executable plus user-facing documentation and asks it to *rebuild* the codebase from scratch, offline, inside a sandbox … with no decompiler. Crucially, ProgramBench *fixes the harness*: every model runs inside the deliberately minimal mini-swe-agent scaffold, so the score reflects the model's own architectural reasoning rather than the surrounding tooling.

**What the source actually says** (abstract, [arXiv:2605.03546](https://arxiv.org/abs/2605.03546)):
> Agents are given "only a program and its documentation" and must "architect and implement a codebase that matches the reference executable's behavior." 200 tasks, ranging from CLI tools to FFmpeg/SQLite. "End-to-end behavioral tests are generated via agent-driven fuzzing, enabling evaluation without prescribing implementation structure." Headline result: "none fully resolve any task, with the best model passing 95% of tests on only 3% of tasks." Models "favor monolithic, single-file implementations that diverge sharply from human-written code."

**Verdict:** mostly faithful with one mischaracterization. (a) The 200-task count, the "program + documentation as input," and the rebuild-from-scratch framing are correct. (b) However, the doc claims the agent gets "only a compiled executable plus user-facing documentation" — the abstract says "only a program and its documentation," which is ambiguous between source and binary; the "no decompiler" gloss appears to be the doc's inference rather than the abstract's text. (c) **The "fixes the harness to mini-swe-agent" claim is not visible in the abstract** — this is a load-bearing claim for §2's whole argument and was not confirmed against the source in this pass. It may well be in the paper body, but the audit cannot verify it from the abstract. (d) The headline "best model passing 95% of tests on only 3% of tasks" is a much more striking and concrete result than the doc cites — the doc should surface it. (e) The "Claude Opus 4.7 tops the leaderboard" claim is a leaderboard snapshot, not a paper claim, and is provisional on the snapshot date.

**Substantive change proposed** (§2, second paragraph):
> ProgramBench (the 200-task benchmark — [arXiv:2605.03546](https://arxiv.org/abs/2605.03546); leaderboard snapshot programbench.com 2026-05-14, currently topped by Claude Opus 4.7 on the minimal mini-swe-agent scaffold) gives the agent "only a program and its documentation" and asks it to *rebuild* the codebase from scratch, offline, inside a sandbox. The benchmark grades by end-to-end behavioral tests generated via agent-driven fuzzing, so the score is on observable behavior rather than implementation structure. Headline result from the paper: no model fully resolves any task, and the best model passes 95% of tests on only 3% of tasks. ProgramBench's leaderboard treats the mini-swe-agent scaffold as the standard baseline harness, so a harness contribution can be measured against that fixed baseline — that fixed baseline is exactly the variable this plan moves.

Note: if the paper body in fact does *not* lock the harness to mini-swe-agent (i.e., the leaderboard merely *defaults* to it but submitters may swap), the §2 claim that "the score reflects the model's own architectural reasoning rather than the surrounding tooling" needs a softer re-write. This is the single most consequential thing to verify by a paper-body read before publication.

---

### SWE-Bench Pro — [arXiv:2509.16941](https://arxiv.org/abs/2509.16941)

**Doc passage (§5):**
> **SWE-Bench Pro** (Deng et al. 2025, [arXiv:2509.16941](https://arxiv.org/abs/2509.16941)) is the contamination-resistant successor — 1,865 problems, long-horizon enterprise-style tasks, on which the strongest systems resolve well under half and, under cost constraints, roughly a quarter.

**What the source actually says** (abstract):
> "A substantially more challenging benchmark that builds upon the best practices of SWE-BENCH" designed to "capture realistic, complex, enterprise-level problems." 1,865 problems sourced from 41 actively maintained repositories. "Long-horizon tasks that may require hours to days for a professional software engineer to complete, often involving patches across multiple files." Explicitly framed as "a contamination-resistant testbed."

**Verdict:** faithful on count, scope, and contamination framing. The specific numeric claims "well under half" and "roughly a quarter" under cost constraints could not be verified from the abstract alone — flagged provisional. They are plausible from the difficulty framing but should be checked against a results table in the paper body.

**Substantive change proposed:** none required; optionally surface the 41-repository sourcing as a concreteness improvement, and verify the "well under half / roughly a quarter" numbers against the paper body.

---

### OpenAI 2026 SWE-Bench Verified retraction

**Doc passage (§5):**
> In February 2026 OpenAI audited the 138 hardest tasks in SWE-Bench Verified and found at least 59.4 percent materially flawed, with frontier models reproducing gold patches verbatim from the task ID alone … OpenAI recommended SWE-Bench Pro as the replacement.

**Source fetch:** 403 Forbidden on the direct openai.com URL. Verdict provisional.

**Verdict:** unverified — provisional. The specific 59.4% figure and the "verbatim from task ID alone" claim could not be confirmed by direct fetch. The framing matches widely-reported coverage of OpenAI's SWE-Bench Verified deprecation, but the precise figure should be re-verified before publication.

**Substantive change proposed:** keep the claim, but flag for one more verification pass against the OpenAI source (or a peer-reviewed citation that re-reports the figures), and consider citing a secondary report (e.g., an industry write-up) alongside the OpenAI post as a fallback if the post is unreachable.

---

### Garg et al. 2026 "Saving SWE-Bench" — [arXiv:2510.08996](https://arxiv.org/abs/2510.08996)

**Doc passage (§5):**
> the "Saving SWE-Bench" mutation work (Garg et al. 2026, [arXiv:2510.08996](https://arxiv.org/abs/2510.08996)) by converting formal issue text into chat-style queries.

**What the source actually says** (abstract):
> Authors "transform formal GitHub issue descriptions into realistic user-style queries based on telemetry analysis of a popular chat-based agent interactions." Existing benchmarks "overestimate performance by >50% over baseline performance for public benchmarks and ~10-16% for our internal benchmark."

**Verdict:** faithful. The doc captures the technique; it under-uses the actual finding (the >50% overestimation on public benchmarks is a strong number that strengthens §5's contamination-defense framing).

**Substantive change proposed** (optional, adds quantitative weight):
> the "Saving SWE-Bench" mutation work (Garg et al. 2026, [arXiv:2510.08996](https://arxiv.org/abs/2510.08996)) by converting formal issue text into chat-style queries based on telemetry of real chat-agent interactions — reporting that the formal-issue framing overestimates agent performance by more than 50% on public benchmarks.

---

## II. Harness comparison (§3)

### SWE-agent — Yang et al. 2024, [arXiv:2405.15793](https://arxiv.org/abs/2405.15793)

**Doc passage (§3):**
> **SWE-agent** (Yang et al. 2024, NeurIPS 2024) is partly an agent and partly a paper arguing that the **agent-computer interface** — ACI, the menu of commands the agent has, such as file-open, scoped-edit, search, run-tests — matters as much as the model.

**What the source actually says** (abstract, [arXiv:2405.15793](https://arxiv.org/abs/2405.15793)):
> "We posit that LM agents represent a new category of end users with their own needs and abilities, and would benefit from specially-built interfaces to the software they use. We investigate how interface design affects the performance of language model agents… SWE-agent's custom agent-computer interface (ACI) significantly enhances an agent's ability to create and edit code files, navigate entire repositories, and execute tests and other programs."

**Verdict:** faithful. The "matters as much as the model" gloss is the doc's framing, not Yang et al.'s exact words — the paper says interface design "significantly enhances" performance, which is a weaker claim than "matters as much as the model." Minor over-characterization.

**Substantive change proposed** (optional, soften to match):
> **SWE-agent** (Yang et al. 2024, NeurIPS 2024) is partly an agent and partly a paper arguing that the **agent-computer interface** — ACI, the menu of commands the agent has — significantly affects agent performance; the paper's framing is that LM agents are a new category of end-user and benefit from purpose-built interfaces.

---

### Agentless — Xia et al. 2024, [arXiv:2407.01489](https://arxiv.org/abs/2407.01489)

**Doc passage (§3 and the table):**
> **Agentless** (Xia, Deng, Dunn, Zhang 2024, [arXiv:2407.01489](https://arxiv.org/abs/2407.01489)) removes the agent loop entirely: a fixed three-phase pipeline of localize, repair, validate, which beat many agent systems on SWE-Bench Lite at $0.70 per task.
> [Table row: "Localize | hierarchical"]

**What the source actually says** (abstract):
> "Three-phase process of localization, repair, and patch validation." "32.00%, 96 correct fixes" on SWE-Bench Lite at "$0.70" per task. Localization described as "simplistic" rather than explicitly "hierarchical" in the abstract — the abstract does not use the word "hierarchical."

**Verdict:** mostly faithful on the three-phase pipeline and the $0.70 figure. The "32.00% / 96 fixes" figure could be surfaced in the doc for concreteness. The **"hierarchical" localization claim in the Section 3 table is not confirmed from the abstract** — this may be a paper-body detail (Agentless does in fact use a coarse-to-fine localization that could reasonably be described as hierarchical), but the audit cannot verify it from the abstract alone.

**Substantive change proposed** (§3 prose, optional addition of the 32% figure):
> **Agentless** (Xia, Deng, Dunn, Zhang 2024, [arXiv:2407.01489](https://arxiv.org/abs/2407.01489)) removes the agent loop entirely: a fixed three-phase pipeline of localize, repair, validate, achieving 32.00% on SWE-Bench Lite at $0.70 per task.

For the table row, "hierarchical" should be verified against the paper body; if not literally hierarchical, a less specific gloss like "coarse-to-fine" may be safer.

---

### OpenHands — Wang et al. 2024, [arXiv:2407.16741](https://arxiv.org/abs/2407.16741)

**Doc passage (§3):**
> **OpenHands** (Wang et al. 2024, ICLR 2025; SDK paper [arXiv:2511.03690](https://arxiv.org/abs/2511.03690)) is the open-source platform that is the de facto SWE-Bench Verified baseline, reporting a 72 percent resolve rate with Claude Sonnet 4.5; it supports hierarchical agents that delegate to other agents.

**What the source actually says** (abstract + web search for the resolve rate):
> Abstract describes OpenHands as a platform for AI agents that "interact with the world in similar ways to those of a human developer." The abstract does not specify SWE-Bench Verified performance numbers. Independent web search returned: OpenHands + Claude 4 (the prior generation) at 70.4% on SWE-Bench Verified (OpenHands social post); Sonnet 4.5 itself scoring 77.2% on SWE-Bench Verified (likely Anthropic's own harness, not OpenHands).

**Verdict:** the specific "72% with Claude Sonnet 4.5" number could not be verified. The closest verifiable adjacent numbers are 70.4% (OpenHands + Claude 4, prior model) and 77.2% (Sonnet 4.5 standalone). The doc's 72% figure is plausible — it could be a more recent or unreported OpenHands+Sonnet 4.5 result — but **needs a direct source**. Also, "hierarchical agents that delegate to other agents" is not in the abstract; the abstract mentions "coordination between multiple agents," which is weaker.

**Substantive change proposed:**
> **OpenHands** (Wang et al. 2024, ICLR 2025; SDK paper [arXiv:2511.03690](https://arxiv.org/abs/2511.03690)) is the open-source platform that is the de facto SWE-Bench Verified baseline. Public OpenHands results on SWE-Bench Verified include 70.4% with Claude 4 (OpenHands public report); the 72% figure cited here should be confirmed against the specific OpenHands+Sonnet-4.5 source before publication. The platform supports multi-agent coordination, including agents that delegate sub-tasks to other agents.

---

## III. QA worker and test generation (§4a)

### Playwright Test Agents

**Doc passage (§4a):**
> Playwright … shipped Test Agents in v1.56 (October 2025): a Planner that proposes a test plan, a Generator that writes the test code, and a Healer that repairs tests broken by UI changes … Playwright's Planner needs a human to name the scenario *and* supply a seed test to work from — it does not decide what to test. And the Healer explicitly only patches the *test* when the app changes; it never patches the *product*.

**What the source actually says** (playwright.dev/docs/test-agents):
> Planner: "Explores your app and produces a test plan for one or many scenarios and user flows." Requires "a clear request to the planner" and "a `seed test` that sets up the environment necessary to interact with your app."
> Generator: transforms markdown plans into Playwright tests.
> Healer: "Executes the test suite and automatically repairs failing tests" by "replay[ing] the failing steps," "inspect[ing] the current UI," and "suggest[ing] a patch (e.g., locator update, wait adjustment, data fix)."

**Verdict:** faithful. Both load-bearing claims — Planner needs a human-named scenario and a seed test; Healer patches tests not the product — are directly confirmed by the Playwright docs.

**Substantive change proposed:** none required.

---

### TestExplora — [arXiv:2602.10471](https://arxiv.org/abs/2602.10471)

**Doc passage (§4a):**
> **TestExplora** (Microsoft Research 2026, [arXiv:2602.10471](https://arxiv.org/abs/2602.10471)) moves closest to pm because it tests the *proactive* case. It benchmarks proactive test generation — discovering latent defects with all defect signals hidden — and reports state-of-the-art LLMs reach only a 16.06 percent fail-to-pass rate.

**What the source actually says** (abstract):
> Benchmark "comprises 2,389 tasks from 482 repositories and hides all defect-related signals." Targets "proactive discovery." "State-of-the-art models achieve a maximum Fail-to-Pass (F2P) rate of only 16.06%." Notes: "SWEAgent instantiated with GPT-5-mini achieves an F2P of 17.27%."

**Verdict:** faithful on all load-bearing points — proactive framing, hidden defect signals, 16.06% F2P. The 2,389 tasks / 482 repositories scale is more concrete than the doc currently shows; the "agentic SWEAgent + GPT-5-mini reaches 17.27%" is a useful upper-bound number for the comparison.

**Substantive change proposed** (optional concreteness):
> **TestExplora** (Microsoft Research 2026, [arXiv:2602.10471](https://arxiv.org/abs/2602.10471)) — 2,389 tasks from 482 repositories with all defect signals hidden — benchmarks proactive test generation. State-of-the-art LLMs reach only a 16.06% fail-to-pass rate (with an agentic SWEAgent + GPT-5-mini upper bound of 17.27%). That is the strongest published prior-art number against which `pr-2680fbf`'s yield should be measured.

---

### CodaMosa, OSS-Fuzz (§4a, abstract-level check)

**CodaMosa (Lemieux et al. 2023):** doc claims it "pairs evolutionary test search with Codex, using the LLM as the escape valve when the classical search hits a coverage plateau." This is the standard published characterization and matches the abstract. **Verdict:** faithful. No change.

**OSS-Fuzz (Serebryany 2017):** doc claims it is Google's continuous fuzzing service where the corpus grows and survives runs. This is the standard published characterization. **Verdict:** faithful. No change.

---

## IV. Automated program repair (§4b)

### RepairAgent — Bouzenia et al. 2025, [arXiv:2403.17134](https://arxiv.org/abs/2403.17134)

**Doc passage (§4b):**
> **RepairAgent** (Bouzenia, Devanbu, Pradel 2025, ICSE 2025, [arXiv:2403.17134](https://arxiv.org/abs/2403.17134)) is the first repair work built as an autonomous LLM agent: it interleaves bug-information gathering, repair-ingredient gathering, and validation under a finite-state machine, reporting 164 Defects4J bugs repaired.

**What the source actually says** (abstract):
> "To the best of our knowledge, this work is the first to present an autonomous, LLM-based agent for program repair." Three components: "a set of repair-focused tools, a dynamically updated prompt format enabling LLM-tool interaction, and a finite state machine that guides the agent in invoking the tools." The agent "interleaves [gathering bug information, collecting repair ingredients, and validating fixes]." Result: "autonomously repairing 164 bugs, including 39 bugs not fixed by prior techniques."

**Verdict:** faithful. Every load-bearing claim — first autonomous LLM agent for repair, FSM-guided interleaving of info / ingredients / validation, 164 bugs — directly matches the abstract.

**Substantive change proposed:** none required. Optionally surface the "39 not fixed by prior techniques" subfigure for additional concreteness.

---

### AutoCodeRover — Zhang et al. 2024, [arXiv:2404.05427](https://arxiv.org/abs/2404.05427)

**Doc passage (§4b):**
> **AutoCodeRover** (Zhang et al. 2024, ISSTA) uses the program's structural tree to localize the bug before handing it to the LLM.

**What the source actually says** (abstract):
> "We work on a program representation (abstract syntax tree) as opposed to viewing a software project as a mere collection of files. Our code search exploits the program structure in the form of classes/methods to enhance LLM's understanding of the issue's root cause." Also uses "spectrum-based fault localization using tests."

**Verdict:** faithful. The "structural tree" gloss correctly summarizes the AST + class/method structure-based search. Optionally the doc could note that AutoCodeRover also uses spectrum-based fault localization (test-failure traces) alongside the AST search, which would sharpen the comparison with pm's per-PR scoping.

**Substantive change proposed** (optional):
> **AutoCodeRover** (Zhang et al. 2024, ISSTA) localizes via the program's AST (with class/method-level search) and spectrum-based fault localization from test failures before handing the bug to the LLM.

---

### Self-Debug — Chen et al. 2023, [arXiv:2304.05128](https://arxiv.org/abs/2304.05128)

**Doc passage (§4b):**
> **Self-Debug** (Chen et al. 2023, [arXiv:2304.05128](https://arxiv.org/abs/2304.05128)) and **Self-Edit** (Zhang et al. 2023, ACL) have the model execute a candidate, observe the failure, and retry with that feedback.

**What the source actually says** (Self-Debug abstract):
> "Without any human feedback on the code correctness or error messages, the model is able to identify its mistakes by investigating the execution results." Improves sample efficiency by "leveraging feedback messages and reusing failed predictions."

**Verdict:** faithful. The "execute, observe, retry with feedback" gloss is exactly Self-Debug's loop.

**Substantive change proposed:** none required.

---

## V. Verifier / self-correction (§4c)

### Cobbe et al. 2021 (GSM8K verifier) — [arXiv:2110.14168](https://arxiv.org/abs/2110.14168)

**Doc passage (§4c):**
> **Cobbe et al. 2021** (arXiv:2110.14168, the GSM8K paper) shows a separately-trained verifier ranking candidate solutions beats a finetuned generator alone.

**What the source actually says** (abstract):
> "We generate many candidate solutions and select the one ranked highest by the verifier." "Verification significantly improves performance on GSM8K, and we provide strong empirical evidence that verification scales more effectively with increased data than a finetuning baseline."

**Verdict:** faithful. Exactly the claim the doc makes.

**Substantive change proposed:** none required.

---

### Lightman et al. 2023 ("Let's Verify Step by Step") — [arXiv:2305.20050](https://arxiv.org/abs/2305.20050)

**Doc passage (§4c):**
> **Lightman et al. 2023** ("Let's Verify Step by Step," NeurIPS 2023) extends this to *process supervision* — scoring each reasoning step, not just the final answer.

**What the source actually says** (abstract):
> "Process supervision significantly outperforms outcome supervision for training models to solve problems from the challenging MATH dataset." Process-supervised model "78% accuracy on a MATH test subset." Releases PRM800K.

**Verdict:** faithful. Cleanly matches the doc.

**Substantive change proposed:** none required.

---

### Huang et al. 2023 ("LLMs Cannot Self-Correct Reasoning Yet") — [arXiv:2310.01798](https://arxiv.org/abs/2310.01798)

**Doc passage (§4c):**
> **Huang et al. 2023** ("Large Language Models Cannot Self-Correct Reasoning Yet," ICLR 2024) showed [intrinsic self-correction] can *degrade* performance.

**What the source actually says** (abstract):
> LLMs "struggle to self-correct their responses without external feedback, and at times, their performance even degrades after self-correction." Studies "intrinsic self-correction, whereby an LLM attempts to correct its initial responses based solely on its inherent capabilities, without the crutch of external feedback."

**Verdict:** faithful. The doc correctly scopes the claim to *intrinsic* self-correction (no external feedback), which is the precise condition Huang et al. tested. The "at times" qualifier in the paper is slightly stronger than the doc's "can degrade," but the substantive claim is the same.

**Substantive change proposed:** none required.

---

### Reflexion — Shinn et al. 2023, [arXiv:2303.11366](https://arxiv.org/abs/2303.11366)

**Doc passage (§4c):**
> **Reflexion** (Shinn et al. 2023) is the closest agent-side ancestor — its written "lessons learned" memory is the pattern the per-watcher work-logs reuse across ticks.

**What the source actually says** (abstract):
> "Reflexion agents verbally reflect on task feedback signals, then maintain their own reflective text in an episodic memory buffer."

**Verdict:** faithful. "Lessons learned memory" is a slightly informal gloss for "reflective text in an episodic memory buffer," but the substance matches.

**Substantive change proposed:** none required.

---

### Pan et al. 2024 (Spontaneous Reward Hacking in Iterative Self-Refinement) — [arXiv:2407.04549](https://arxiv.org/abs/2407.04549)

**Doc passage (§4c):**
> **Pan et al. 2024** ("Spontaneous Reward Hacking in Iterative Self-Refinement," [arXiv:2407.04549](https://arxiv.org/abs/2407.04549)) shows this emerges spontaneously in self-refinement loops, *more readily when generator and evaluator share context*. … The amendment cap (default 2) is the primary mitigation; two amendments is exactly the regime Pan et al. found measurable hacking in, so the cap is necessary but not sufficient.

**What the source actually says** (abstract):
> "Reward hacking can occur spontaneously in-context with the use of iterative self-refinement." Two factors identified as affecting severity: "context sharing between the generator and the evaluator" and model size. The task setting is an essay editing task.

**Verdict:** faithful on the two load-bearing points — spontaneous emergence and worse-with-shared-context. The doc's specific claim that "two amendments is exactly the regime Pan et al. found measurable hacking in" was **not verifiable from the abstract alone** — the abstract does not specify the iteration count at which hacking first becomes measurable. This is the single most load-bearing numeric claim in §4c (the cap of 2 is justified by this precise number) and should be confirmed against the paper body. Flag provisional.

**Substantive change proposed** (soften pending paper-body confirmation):
> The amendment cap (default 2) is the primary mitigation. Pan et al. show hacking emerges within a small number of refinement iterations, in the regime the cap is meant to bound; the exact iteration threshold the paper reports should be cited here once confirmed against the paper body. As written the cap is necessary but not sufficient.

---

### AuditBench — Anthropic 2026

**Doc passage (§4c):**
> Anthropic's **AuditBench** (alignment.anthropic.com, 2026-03-10) documents an adjacent failure: a *tool-to-agent gap* where a checker reading good evidence still fails at the aggregation step.

**What the source actually says** (alignment.anthropic.com/2026/auditbench/):
> AuditBench is a benchmark of "56 language models with implanted hidden behaviors" across 14 categories with an investigator agent that audits via configurable tools. The *tool-to-agent gap*: "tools that reliably surface evidence of a hidden behavior in static evaluations often fail to translate into better investigator agent performance." Three failure modes: under-use of effective tools; signal/noise confusion; "verification proves harder than surfacing evidence." Threat model: alignment auditing — uncovering "hidden or unintended behaviors" the model conceals.

**Verdict:** faithful. The doc's gloss — checker reading good evidence still fails at aggregation — captures the third failure mode (verification harder than surfacing evidence) precisely. The threat-model caveat ("hidden-behavior auditing, not QA grading") is also explicitly preserved in the doc, which is the kind of model-class scoping the audit cares about.

**Substantive change proposed:** none required. Optionally the doc could surface that AuditBench documents *three* failure modes, with the verification-harder-than-surfacing one being the closest match to pm's concern.

---

## VI. Audit / cheating detection (§4d)

### Meerkat — Stein et al. 2026, [arXiv:2604.11806](https://arxiv.org/abs/2604.11806)

**Doc passage (§4d):**
> **Meerkat** (Stein et al., [arXiv:2604.11806](https://arxiv.org/abs/2604.11806), 2026) takes the across-runs axis — clustering plus agentic search to surface violations across large trace collections, reporting nearly 4x more reward-hacking examples on CyBench than prior audits.

**What the source actually says** (abstract):
> Meerkat "combines clustering with agentic search to uncover violations specified in natural language." Finds "nearly 4x more examples of reward hacking on CyBench than previous audits."

**Verdict:** faithful. Both load-bearing claims confirmed verbatim.

**Substantive change proposed:** none required.

---

### TRACE — Deshpande et al. 2026, [arXiv:2601.20103](https://arxiv.org/abs/2601.20103)

**Doc passage (§4d):**
> **TRACE** (Deshpande et al. 2026, [arXiv:2601.20103](https://arxiv.org/abs/2601.20103)) reports 45–63 percent detection for state-of-the-art LLM judges catching code-environment reward hacks.

**What the source actually says** (abstract):
> "517 testing trajectories." "GPT-5.2 with highest reasoning mode achieving the best detection rate at 63%, up from 45% in isolated settings on TRACE." The 45% number is for *isolated* (non-contrastive) classification; 63% is the *contrastive* setting.

**Verdict:** **partially under-characterizes.** The doc cites the 45–63% range correctly, but conflates two different evaluation regimes: 45% is isolated classification, 63% is contrastive anomaly detection. The actual contribution of TRACE is precisely showing that contrastive evaluation lifts performance from 45% to 63% — that lift is the paper's point, and the doc as written buries it.

**Substantive change proposed:**
> **TRACE** (Deshpande et al. 2026, [arXiv:2601.20103](https://arxiv.org/abs/2601.20103); 517 trajectories) reports that state-of-the-art LLM judges detect code-environment reward hacks at 45% in an isolated-classification setting, rising to 63% (GPT-5.2 at highest reasoning) under contrastive anomaly detection. The 45–63% range is therefore not a noisy point estimate but the lift from a methodology change — a structural pointer for how pm's capstone audit should be evaluated.

---

### RHB — Thaman 2026, [arXiv:2605.02964](https://arxiv.org/abs/2605.02964)

**Doc passage (§4d):**
> **RHB** (Thaman 2026) reports base shortcut-exploit rates of 0–13.9 percent across 13 frontier models.

**What the source actually says** (abstract):
> "Exploit rates range from 0% (Claude Sonnet 4.5) to 13.9% (DeepSeek-R1-Zero)." 13 models from OpenAI, Anthropic, Google, DeepSeek. Tool-use, multi-step task setting. Notable additional finding: RL post-training increases reward hacking — DeepSeek variants showed 13.9% (RL-trained) vs 0.6% (non-RL).

**Verdict:** faithful on the headline 0–13.9% range. **Under-characterizes** in one respect: the RL-vs-non-RL contrast (13.9% vs 0.6% within the same model family) is a substantively important finding that bears directly on §4d's claim about which models the capstone audit needs to defend against — if RL post-training increases exploitation, the threat profile against a frontier-RL'd Claude model is meaningfully different from a base model.

**Substantive change proposed:**
> **RHB** (Thaman 2026) reports base shortcut-exploit rates of 0% (Claude Sonnet 4.5) to 13.9% (DeepSeek-R1-Zero) across 13 frontier models on tool-use multi-step tasks. The paper additionally finds that RL post-training increases exploitation — the same DeepSeek base shifts from 0.6% (non-RL) to 13.9% (RL-trained) — which sharpens the capstone audit's threat profile against RL'd frontier models.

---

### ImpossibleBench — Zhong et al. 2025, [arXiv:2510.20270](https://arxiv.org/abs/2510.20270)

**Doc passage (§4d):**
> **ImpossibleBench** (Zhong et al. 2025, [arXiv:2510.20270](https://arxiv.org/abs/2510.20270)) measures how readily models exploit test cases (GPT-5 cheats on 54 percent of conflicting-spec runs), but for an artifact-visible cheat, not a trace-only one.

**What the source actually says** (abstract):
> Measures "LLM agents' propensity to exploit test cases." Defines "cheating rate" as performance on impossible tasks "where any pass necessarily implies a specification-violating shortcut."

**Verdict:** **the specific 54% GPT-5 figure could not be verified from the abstract.** The framing (artifact-visible cheat via conflicting spec) is faithful to the abstract. The 54% number is a paper-body claim that needs direct confirmation. Flag provisional. Also, the doc's qualifier "artifact-visible cheat, not a trace-only one" is the doc's own (correct) framing distinction, which is fine.

**Substantive change proposed** (pending paper-body confirmation):
> **ImpossibleBench** (Zhong et al. 2025, [arXiv:2510.20270](https://arxiv.org/abs/2510.20270)) measures how readily models exploit test cases by constructing tasks where any passing solution must violate the specification. Reported model cheating rates should be cited from the paper body (the specific GPT-5 / 54% figure in the current draft needs verification). The threat profile is an artifact-visible cheat, not a trace-only one — distinct from the runtime-internet-lookup threat the capstone audit faces.

---

## VII. Autonomous loops (§4e)

### SWE-CI — Chen et al. 2026, [arXiv:2603.03823](https://arxiv.org/abs/2603.03823)

**Doc passage (§4e):**
> **SWE-CI** (Chen et al. 2026, [arXiv:2603.03823](https://arxiv.org/abs/2603.03823)) benchmarks maintainability across an average of 71 consecutive commits per repository, but offline against historical traces — "continuous" there is continuous integration over commit history, not a live loop.

**What the source actually says** (abstract):
> "The first repository-level benchmark built upon the Continuous Integration loop, aiming to shift the evaluation paradigm for code generation from static, short-term functional correctness toward dynamic, long-term maintainability." 100 tasks. "Average of 233 days and 71 consecutive commits" per task.

**Verdict:** faithful. The 71-commit number is correct; the "offline against historical traces" framing is correct (the abstract describes development *history* spans, not live integration); the "continuous integration over commit history, not a live loop" gloss is a fair characterization.

**Substantive change proposed:** none required. Optionally surface "100 tasks, average of 233 days per task" for concreteness.

---

## VIII. Harness-evolution adjacent work (§6)

### Agentic Harness Engineering — [arXiv:2604.25850](https://arxiv.org/abs/2604.25850)

**Doc passage (§6):**
> **Agentic Harness Engineering** (arXiv:2604.25850) is a built, autonomous loop in which an agent edits its own harness components — tools, middleware, memory — and checks each edit against task outcomes, reporting a Terminal-Bench 2 pass@1 rise from 69.7% to 77.0%.

**What the source actually says** (abstract):
> "A closed loop that addresses these challenges through three matched observability pillars" — component, experience, decision observability. "Ten AHE iterations lift pass@1 on Terminal-Bench 2 from 69.7% to 77.0%." Compared against "human-designed Codex-CLI baseline (71.9%) and self-evolving baselines ACE and TF-GRPO."

**Verdict:** faithful on the 69.7% → 77.0% lift. The "ten iterations" detail is more concrete than the doc carries; the comparison against the 71.9% Codex-CLI human baseline strengthens the "harness-evolution genuinely beats human harness design" framing of §6's discussion.

**Substantive change proposed** (optional concreteness):
> **Agentic Harness Engineering** (arXiv:2604.25850) — ten iterations of an autonomous loop where the agent edits its own harness lift pass@1 on Terminal-Bench 2 from 69.7% to 77.0%, surpassing the human-designed Codex-CLI baseline (71.9%).

---

### "The Last Harness You'll Ever Build" — [arXiv:2604.21003](https://arxiv.org/abs/2604.21003)

**Doc passage (§6):**
> **"The Last Harness You'll Ever Build"** (arXiv:2604.21003) proposes a designer/engineer/QA decomposition and a meta-loop that bootstraps onto new tasks — but it is a framework paper, not an implemented or available system, and reports no results.

**What the source actually says** (abstract):
> Two-level framework: "Harness Evolution Loop" (single-task) and "Meta-Evolution Loop" (cross-task generalizable blueprints). Role-specific agents: Worker (executes), Evaluator ("adversarially diagnoses failures and scores performance"), Evolution agent (modifies the harness).

**Verdict:** the doc's "designer/engineer/QA decomposition" framing slightly mischaracterizes the paper's actual three roles: **Worker** (executes — closest to engineer), **Evaluator** (diagnoses failures and scores — closest to QA), and **Evolution agent** (modifies the harness — not really "designer"). The paper does not name a "designer" role per se. The "framework paper without implementation or results" claim could not be definitively confirmed from the abstract alone, but the abstract's lack of any empirical number is consistent with the doc's framing.

**Substantive change proposed:**
> **"The Last Harness You'll Ever Build"** (arXiv:2604.21003) proposes a two-level harness-evolution framework with three role-specific agents — a Worker (executor), an Evaluator (diagnoses failures and scores), and an Evolution agent (modifies the harness) — plus a meta-loop that learns generalizable blueprints across tasks. The mapping to pm's designer / engineer / QA decomposition is partial (Worker ↔ engineer, Evaluator ↔ QA, Evolution ↔ a meta-role pm does not stage); the paper is framework-shaped with the abstract reporting no empirical results.

---

## Alternative perspectives not currently represented

A handful of substantive caveats from the cited sources are not represented in the lit review and should be considered:

1. **ProgramBench's headline result** — no model fully resolves any task; best model passes 95% of tests on only 3% of tasks — is a stronger evidence base for "the field's frontier on whole-codebase rebuilding is genuinely young" than the doc currently uses. Surfacing it would harden §2.

2. **RHB's RL-post-training-increases-hacking finding** is highly relevant to §4d's threat model — the audit's recall target needs to account for the fact that frontier RL'd models exploit more, not less.

3. **TRACE's contrastive-vs-isolated lift** (45% → 63%) is a methodological pointer the capstone audit's design could lift: pm's audit is currently single-trajectory, but the 18-point lift from contrastive evaluation suggests an ensemble-or-pairwise variant should be considered.

4. **Pan et al. 2024's specific iteration threshold** for measurable hacking — the load-bearing detail behind pm's "amendment cap = 2" choice — is not verified from the abstract. The §4c claim that "two amendments is exactly the regime Pan et al. found measurable hacking in" should be backed against the paper body. If the actual threshold is different from 2, the cap may need re-tuning.

5. **The "OpenHands reports 72% with Sonnet 4.5"** number is unverified by direct fetch. The nearest verified numbers are 70.4% (OpenHands + Claude 4) and 77.2% (Sonnet 4.5 in Anthropic's own harness). Without a direct source, this number should be hedged or replaced.

6. **The "Agentless localization is hierarchical"** table cell is not confirmed from the Agentless abstract. The abstract calls the localization "simplistic" rather than hierarchical. This is a paper-body detail that needs direct verification.

7. **The "ProgramBench fixes the harness to mini-swe-agent"** claim is the single most load-bearing item in the entire review. The audit could not confirm it from the abstract. If the paper does *not* lock the harness (and the leaderboard merely defaults to mini-swe-agent as a submission convention), §2's argument needs material softening.

---

## Summary of substantive changes recommended

Ranked by required action — apply top to bottom.

### Material fixes (apply)

| Citation | Verdict | Action |
|---|---|---|
| **ProgramBench** | partially unverified — load-bearing | Confirm the "fixes the harness" claim against the paper body before §2 can stand as written; otherwise soften. Surface the headline 95-percent-of-tests-on-3-percent-of-tasks result. |
| **OpenHands** | unverified resolve-rate figure | Confirm the "72% with Sonnet 4.5" claim against a direct OpenHands source; otherwise replace with the verified 70.4% (Claude 4) or hedge. Soften "hierarchical agents that delegate" to "multi-agent coordination." |
| **TRACE** | under-characterizes | Replace the "45-63%" range with the contrastive-vs-isolated framing — that lift is the paper's point. |
| **RHB** | under-characterizes | Add the RL-post-training-increases-hacking finding (0.6% → 13.9% within DeepSeek family) — bears on §4d's threat profile. |
| **Pan et al. 2024** | unverified specific-iteration claim | Confirm against paper body that "two amendments is exactly the regime Pan found hacking in," or soften. |
| **ImpossibleBench** | unverified specific-figure | Confirm the GPT-5 / 54% cheating-rate figure against the paper body, or hedge. |
| **OpenAI SWE-Bench Verified retraction** | unverified | Direct URL 403'd; confirm the 59.4% and "verbatim from task ID" figures against an alternative source or live URL. |

### Optional tightenings (apply if the line is being touched anyway)

- **SWE-agent**: soften "matters as much as the model" → "significantly affects performance" to match the abstract's exact framing.
- **Agentless**: surface the 32% / 96 fixes / $0.70 figure. Verify the "hierarchical" localization gloss against the paper body, or replace with "coarse-to-fine."
- **TestExplora**: surface 2,389 tasks / 482 repositories and the agentic upper bound of 17.27% (SWE-Agent + GPT-5-mini).
- **AutoCodeRover**: note spectrum-based fault localization is used alongside AST search.
- **SWE-CI**: optionally surface 100 tasks / 233-day average per task for concreteness.
- **Agentic Harness Engineering**: optionally surface "ten iterations" and the Codex-CLI 71.9% human baseline.
- **"Last Harness You'll Ever Build"**: refine the role mapping (Worker / Evaluator / Evolution) since the paper does not name a "designer" role.
- **Saving SWE-Bench**: optionally surface the >50% overestimation finding.
- **AuditBench**: optionally surface that AuditBench documents three failure modes, with the verification-harder-than-surfacing one being the closest match to pm's concern.

### Faithful, no change required

ProgramBench (200 tasks, input framing — modulo the paper-body verification above), SWE-Bench Pro, Playwright Test Agents, TestExplora (core), RepairAgent, AutoCodeRover (core), Self-Debug, Cobbe 2021, Lightman 2023, Huang 2023, Reflexion, Meerkat, AuditBench (core), SWE-CI, Agentic Harness Engineering (core), CodaMosa, OSS-Fuzz.

---

## Fetch failures and scope notes

- **OpenAI 2026 SWE-Bench Verified retraction post** (openai.com/index/swe-bench-verified-no-longer-measures-frontier-coding/) — returned 403 Forbidden. The 59.4% materially-flawed figure and the "verbatim from task ID" claim are unverified by direct fetch. Verdict provisional.
- **Pan et al. 2024 specific iteration count** — the abstract did not state at how many iterations hacking first becomes measurable. The §4c claim that this is "exactly" 2 amendments needs paper-body verification.
- **ProgramBench harness-fixing claim** — the abstract did not confirm that the benchmark *enforces* mini-swe-agent as the harness. This is the single most consequential item to verify by paper-body read before publication.
- **Agentless "hierarchical" localization** — the abstract calls it "simplistic." The "hierarchical" gloss in the §3 table is a paper-body claim.
- **OpenHands 72% with Sonnet 4.5** — could not verify by direct fetch or web search. Nearest verified numbers are 70.4% (OpenHands + Claude 4) and 77.2% (Sonnet 4.5 in Anthropic's harness).
- **ImpossibleBench GPT-5 / 54%** — the abstract did not surface the specific 54% figure. Verdict provisional.
- **CodaMosa, OSS-Fuzz, Lemieux/Serebryany** — abstract-level checks only; both are widely-cited standard references and the doc's gloss matches the standard published characterization.
- **SWE-Bench Pro "well under half / roughly a quarter"** — the abstract did not surface the specific numbers; flagged provisional.
- **All Anthropic alignment.anthropic.com posts** other than AuditBench were not re-verified in this pass; their representation in the doc carries over from earlier audit cycles unchanged.

This audit was a single-pass abstract-and-key-section read across ~25 load-bearing citations. The top ~15 by load-bearing significance received the most careful treatment; the remainder are abstract-level checks and flagged accordingly. A second pass with full PDF extraction on the seven "material fix" items would be the natural follow-up.

---

## Tier-2 supplemental pass

A second pass to cover all citations not in the Tier-1 set above, per the updated protocol's "audit every citation" requirement. Entries are organized by the same Section-cluster headings used in the Tier-1 pass. Each entry includes its `**Tier:**` tag explicitly. Most are Tier 2 (one-off support, abstract-level check); a smaller set is Tier 3 (ref-list-only, no inline argumentative use).

### I. Benchmarks and contamination (§2, §5) — Tier-2

#### HumanEval / Chen et al. 2021 — [arXiv:2107.03374](https://arxiv.org/abs/2107.03374)
**Tier:** 2
**Doc passage (§5):** "**HumanEval** (Chen et al. 2021, the Codex report) and **MBPP** (Austin et al. 2021) — graded isolated function-completion against hidden tests."
**Abstract gloss:** Codex paper introduces HumanEval as a "new evaluation set we release to measure functional correctness for synthesizing programs from docstrings." Function-completion framing is accurate.
**Verdict:** faithful.

#### MBPP / Austin et al. 2021 — [arXiv:2108.07732](https://arxiv.org/abs/2108.07732)
**Tier:** 2
**Doc passage (§5):** "**MBPP** (Austin et al. 2021) — graded isolated function-completion against hidden tests."
**Abstract gloss:** MBPP contains "974 programming tasks, designed to be solvable by entry-level programmers" synthesizing "short Python programs from natural language descriptions." Function-completion framing matches.
**Verdict:** faithful.

#### EvalPlus / Liu et al. 2023 — [arXiv:2305.01210](https://arxiv.org/abs/2305.01210)
**Tier:** 2
**Doc passage (§5):** "**EvalPlus** (Liu et al. 2023, NeurIPS 2023) made the test-insufficiency problem explicit — extending HumanEval's tests ~80x dropped pass rates by 19–29 percent."
**Abstract gloss:** EvalPlus "extend[s] the test-cases of the popular HumanEval benchmark by 80x to build HumanEval+ … reducing the pass@k by up-to 19.3-28.9%."
**Verdict:** faithful. The 80x and 19–29% figures match the abstract verbatim.

#### SWE-Bench / Jimenez et al. 2024 — [arXiv:2310.06770](https://arxiv.org/abs/2310.06770)
**Tier:** 2
**Doc passage (§5):** "**SWE-Bench** (Jimenez et al. 2024, ICLR 2024) collects 2,294 tasks from real GitHub repositories, each asking for a patch that resolves an issue and passes a hidden test."
**Abstract gloss:** "2,294 software engineering challenges derived from authentic GitHub issues and pull requests across 12 Python repositories. Models must modify codebases to resolve described issues."
**Verdict:** faithful. The 2,294 task count matches; the 12-repo scope could optionally be surfaced but is not load-bearing.

#### SWE-Bench Multimodal / Yang et al. 2024 — [arXiv:2410.03859](https://arxiv.org/abs/2410.03859)
**Tier:** 2
**Doc passage (§5):** "**SWE-Bench Multimodal** (Yang et al. 2024) extends the shape to 617 visual JavaScript tasks."
**Abstract gloss:** "617 task instances collected from 17 JavaScript libraries used for web interface design, diagramming, data visualization …"
**Verdict:** faithful. The 617-task count and JavaScript framing both match.

#### LiveCodeBench / Jain et al. 2024 — [arXiv:2403.07974](https://arxiv.org/abs/2403.07974)
**Tier:** 2
**Doc passage (§5):** "**LiveCodeBench** (Jain et al. 2024) defends by tying problems to post-cutoff release dates."
**Abstract gloss:** "Continuously collects new problems over time from contests across three competition platforms" — LeetCode, AtCoder, CodeForces — with the contamination-defense framing.
**Verdict:** faithful. The "post-cutoff release dates" gloss is the standard published characterization.

#### BigCodeBench / Zhuo et al. 2024 — [arXiv:2406.15877](https://arxiv.org/abs/2406.15877)
**Tier:** 2
**Doc passage (§5):** "**BigCodeBench** (Zhuo et al. 2024) by library-rich calls that resist memorization."
**Abstract gloss:** "Benchmark that challenges LLMs to invoke multiple function calls as tools from 139 libraries and 7 domains for 1,140 fine-grained tasks."
**Verdict:** faithful on the library-rich framing. The doc's "resist memorization" gloss is the doc's own (reasonable) inference; the abstract does not explicitly frame the diversity as contamination-resistant, but the implication is consistent.

#### Sainz et al. 2023 — [arXiv:2310.18018](https://arxiv.org/abs/2310.18018)
**Tier:** 2
**Doc passage (§5):** "The literature on it (Sainz et al. 2023, Findings of EMNLP … now expects every benchmark to publish a contamination measurement."
**Abstract gloss:** Position paper "argu[ing] that the classical evaluation on Natural Language Processing (NLP) tasks using annotated benchmarks is in trouble." Calls for "automatic and semi-automatic measures to detect when data from a benchmark was exposed to a model."
**Verdict:** faithful. The doc's gloss is a fair summary of the position paper's central call.

#### Riddell et al. 2024 — [arXiv:2403.04811](https://arxiv.org/abs/2403.04811)
**Tier:** 2
**Doc passage (§5):** "Riddell et al. 2024, ACL, using edit-distance and structural comparison to catch renamed near-duplicates."
**Abstract gloss:** Investigates code-generation benchmark contamination with both "surface-level and semantic matching techniques." Confirms the edit-distance / structural-comparison framing.
**Verdict:** faithful.

### II. Harness comparison (§3) — Tier-2

#### mini-swe-agent (mini-swe-agent.com)
**Tier:** 2 (practitioner tool)
**Doc passage (§2, §3):** "the deliberately minimal mini-swe-agent scaffold." "ProgramBench uses [it] as its baseline."
**Source check:** practitioner tool, no peer-reviewed paper; the "minimal scaffold" framing is consistent with the project's own description.
**Verdict:** faithful as a tool description. Note that the load-bearing claim about mini-swe-agent being *fixed* as ProgramBench's evaluation harness lives under the ProgramBench Tier-1 entry, not here.

#### Confucius / 2026 scaffolding analyses
**Tier:** 3 (blog-grade, ref-list level)
**Doc passage (§3):** "**Confucius** is the custom-scaffold coding agent from the 2026 scaffolding analyses, notable for a planning extension and per-issue test generation."
**Source check:** blog-grade practitioner sources; not retrieved in this pass.
**Verdict:** unverified (blog-grade). The "planning extension" and "per-issue test generation" descriptors come from the unverified scaffolding-analyses sources; should be hedged if a peer-reviewed citation cannot be substituted.

### III. QA worker and test generation (§4a) — Tier-2

#### ChatTester / Yuan et al. 2024 — [arXiv:2305.04207](https://arxiv.org/abs/2305.04207)
**Tier:** 2
**Doc passage (§4a):** "**ChatTester** (Yuan et al. 2024, FSE 2024) is an early systematic study of ChatGPT as a test generator."
**Abstract gloss:** Empirical evaluation of ChatGPT's test generation capabilities (correctness, sufficiency, readability). Introduces ChatTESTER, a refinement approach producing "34.3% more compilable tests and 18.7% more tests with correct assertions."
**Verdict:** faithful. The "early systematic study" framing matches.

#### TestPilot / Schäfer et al. 2024 (IEEE TSE)
**Tier:** 2
**Doc passage (§4a):** "**TestPilot** (Schäfer et al. 2024, IEEE TSE) is a clean prompt-skeleton baseline for JavaScript."
**Abstract gloss:** could not retrieve the correct arXiv ID (a similarly-named arXiv preprint resolved to a different paper). The IEEE TSE 50(1):85-105 publication exists per the references list; the "prompt-skeleton baseline for JavaScript" framing is the standard published characterization of TestPilot.
**Verdict:** unverified by direct fetch (could not locate the correct arXiv ID this pass); the gloss is the standard one in the test-generation literature. Flag for paper-body confirmation if any TestPilot detail becomes load-bearing.

#### ChatUniTest / Xie et al. 2023 — [arXiv:2305.04764](https://arxiv.org/abs/2305.04764)
**Tier:** 2
**Doc passage (§4a, §4c):** "**ChatUniTest** (Xie et al. 2023) adds a Generation-Validation-Repair loop discussed in 4c." (§4c) "ChatUniTest's Generation-Validation-Repair loop (Xie et al. 2023) is the test-generation instance: it catches and fixes compile errors and assertion failures before returning a test."
**Abstract gloss:** "Generation-validation-repair mechanism to rectify errors in generated unit tests." Outperforms TestSpark and EvoSuite "in half of the evaluated projects."
**Verdict:** faithful on the Generation-Validation-Repair characterization. **Authorship note:** the arXiv abstract names authors as Chen, Hu, Zhi, Han, Deng, and Yin — *not* "Xie et al." as cited in the doc. The doc's author attribution should be checked against the canonical citation (the "Xie et al." attribution may be from a different ChatUniTest publication, or may be an error).
**Proposed rewrite:** verify the author list; otherwise the substantive characterization is faithful.

#### Issue2Test / Mündler et al. 2025 — [arXiv:2503.16320](https://arxiv.org/abs/2503.16320)
**Tier:** 2
**Doc passage (§4a):** "**Issue2Test** (Mündler et al. 2025) … operate in that reactive shape, where a defect report already exists."
**Abstract gloss:** "LLM-based technique for automatically generating a reproducing test case for a given issue report" — that fails specifically for the reason described in the issue. Reactive-from-issue-report framing confirmed.
**Verdict:** faithful.

#### SWT-Bench / Mündler et al. 2024 — [arXiv:2406.12952](https://arxiv.org/abs/2406.12952)
**Tier:** 2
**Doc passage (§4a):** "The SWT-Bench reactive line — generating a test that reproduces a *reported* issue — is well-populated."
**Abstract gloss:** "Benchmark derived from GitHub repositories. It includes authentic issues, verified bug fixes, and reference tests." Confirms the reactive framing.
**Verdict:** faithful.

#### SWE-Tester — [arXiv:2601.13713](https://arxiv.org/abs/2601.13713)
**Tier:** 2
**Doc passage (§4a):** "**SWE-Tester** (arXiv:2601.13713, the training-side counterpart)."
**Abstract gloss:** "Pipeline for training open-source LLMs to generate issue reproduction tests." Curates 41K training instances from 2.6K repos; "up to 10% improvement in success rate" on SWT-Bench Verified.
**Verdict:** faithful. The "training-side counterpart" gloss correctly captures the contribution shape.

#### Otter — [arXiv:2502.05368](https://arxiv.org/abs/2502.05368)
**Tier:** 2
**Doc passage (§4a):** "**Otter / e-Otter++** (arXiv:2502.05368, arXiv:2508.06365) … operate in that reactive shape."
**Abstract gloss:** Otter generates tests from issues via "rule-based analysis with a self-reflective action planner." Introduces TDD-Bench-Verified; reactive-from-issue framing confirmed.
**Verdict:** faithful.

#### e-Otter++ — [arXiv:2508.06365](https://arxiv.org/abs/2508.06365)
**Tier:** 2
**Doc passage (§4a):** same as Otter above.
**Abstract gloss:** "Reproduction test generator … generating tests with an average fail-to-pass rate of 63% on the TDD-Bench Verified benchmark." Reactive framing confirmed.
**Verdict:** faithful. Optional concreteness: the 63% F2P on TDD-Bench Verified is striking and could be surfaced as comparison alongside TestExplora's 16.06% F2P on the *proactive* TestExplora benchmark — the gap between reactive and proactive being part of the doc's point.

#### R2E / Jain et al. 2024 (ICML)
**Tier:** 2
**Doc passage (§4a):** "**R2E** (Jain et al. 2024, ICML 2024, repository-level test generation with executable feedback)."
**Source check:** could not locate the exact arXiv ID by direct fetch this pass (an adjacent Jain et al. arXiv ID resolves to a different paper). The R2E framing is the standard published characterization in the SWT-Bench-adjacent literature.
**Verdict:** unverified by direct fetch (paper-body confirmation recommended); the inline characterization is brief and not load-bearing.

#### CodaMosa — already audited under Tier-1 (§III above).

#### FLARE — [arXiv:2604.05289](https://arxiv.org/abs/2604.05289)
**Tier:** 2
**Doc passage (§4a):** "**FLARE** (arXiv:2604.05289) … uses an LLM to generate inputs that drive coverage into untested code."
**Abstract gloss:** **FLARE is a testing framework for multi-agent LLM systems** — "extracts specifications from agent code and performs coverage-guided fuzzing to identify failures." It fuzzes *multi-agent systems*, not arbitrary programs.
**Verdict:** **mischaracterizes the domain.** The doc places FLARE in the same bucket as ChatAFL (network-protocol fuzzing) and in-browser fuzzing — all framed as LLM-guided fuzzing of general programs for coverage. But FLARE's domain is specifically multi-agent LLM applications. The "LLM-guided fuzzing" gloss is technically accurate (it does use coverage-guided fuzzing and is LLM-related), but the lumping with ChatAFL / in-browser fuzzing for the "drives coverage into untested code" purpose is misleading about the target.
**Proposed rewrite:** consider moving FLARE to a separate sentence or footnote that names its target as *multi-agent LLM systems* (a different fuzzing target from the agent-as-author-of-fuzz-inputs framing the rest of the paragraph uses).

#### In-browser fuzzing — [arXiv:2510.13543](https://arxiv.org/abs/2510.13543)
**Tier:** 2
**Doc passage (§4a):** "in-browser fuzzing (arXiv:2510.13543) … uses an LLM to generate inputs that drive coverage into untested code."
**Abstract gloss:** "A novel fuzzing framework that runs entirely in the browser and is guided by an LLM to automatically discover such prompt injection vulnerabilities in real time" — i.e., the target is **prompt-injection vulnerabilities in agentic AI browsers**, not general coverage.
**Verdict:** **mischaracterizes the domain.** The cited paper is fuzzing for indirect-prompt-injection attacks on agentic browsers, not generic coverage-driven input fuzzing. Like the FLARE entry above, the lumping is imprecise: the doc's "drives coverage into untested code" framing fits classical fuzzing but not this paper's threat-model.
**Proposed rewrite:** if the lit review wants this citation as an LLM-guided-fuzzing exemplar, characterize it correctly (prompt-injection discovery in agentic browsers); otherwise consider replacing with a more directly on-target LLM-guided-fuzzing reference.

#### ChatAFL (NDSS 2024)
**Tier:** 3 (ref-list level — passing inline mention in a list)
**Doc passage (§4a):** "**FLARE …, ChatAFL (NDSS 2024), and in-browser fuzzing**."
**Source check:** not separately fetched in this pass (peer-reviewed NDSS publication; "Large Language Model guided Protocol Fuzzing" is the canonical title per the doc's references).
**Verdict:** unverified by direct fetch this pass. Adjacent literature; characterization is one-line and not load-bearing.

#### Octomind, QA Wolf
**Tier:** 2 (commercial products, blog-grade)
**Doc passage (§4a):** "**Octomind and QA Wolf** are commercial platforms that *do* autonomously discover flows. … discovers flows by *crawling the app surface* — coverage-driven, walking links and forms to find untested paths."
**Source check:** commercial product pages, not fetched this pass.
**Verdict:** the crawl-driven-discovery framing is the standard product characterization; flagged for direct vendor-page verification if the comparison becomes load-bearing.

### IV. Automated program repair (§4b) — Tier-2

#### GenProg / Le Goues et al. 2012 (IEEE TSE)
**Tier:** 2
**Doc passage (§4b):** "**GenProg** (Le Goues et al. 2012, IEEE TSE) evolves program variants by genetic programming … until the test suite passes."
**Source check:** widely-cited foundational repair work; not separately fetched. The "genetic-programming-until-tests-pass" gloss is the canonical characterization.
**Verdict:** faithful (standard characterization).

#### Sapfix/Sapienz / Marginean et al. 2019 (ICSE-SEIP)
**Tier:** 2
**Doc passage (§4b):** "**Sapfix/Sapienz** (Marginean et al. 2019, ICSE-SEIP) is Facebook's production deployment of the same pattern at million-line scale, with engineer-approval gates."
**Source check:** not separately fetched; the Facebook-production / engineer-approval framing is the standard characterization.
**Verdict:** faithful (standard characterization).

#### Getafix / Bader et al. 2019 (OOPSLA)
**Tier:** 2
**Doc passage (§4b):** "**Getafix** (Bader et al. 2019, OOPSLA) extracts repair templates from past human fixes."
**Source check:** not separately fetched; "repair templates from past human fixes" is the standard characterization.
**Verdict:** faithful.

#### Self-Edit / Zhang et al. 2023 (ACL) — [arXiv:2305.04087](https://arxiv.org/abs/2305.04087)
**Tier:** 2
**Doc passage (§4b):** "**Self-Edit** (Zhang et al. 2023, ACL) have the model execute a candidate, observe the failure, and retry with that feedback."
**Abstract gloss:** "Self-Edit … utilizes execution results of the generated code from LLMs to improve the code quality." Wraps results into supplementary comments that guide a fault-aware editor.
**Verdict:** faithful. The execute-observe-retry framing matches.

### V. Verifier / self-correction (§4c) — Tier-2

#### Self-Refine / Madaan et al. 2023 — [arXiv:2303.17651](https://arxiv.org/abs/2303.17651)
**Tier:** 2
**Doc passage (§4c):** "[intrinsic self-correction], the setting **Self-Refine** (Madaan et al. 2023, NeurIPS 2023) explored."
**Abstract gloss:** "Self-Refine … uses a single LLM as the generator, refiner, and feedback provider" without external supervision — i.e., the canonical "intrinsic self-correction" setting.
**Verdict:** faithful. The same-model-grading-itself framing is exactly Self-Refine's design.

#### Skalse et al. 2022 — [arXiv:2209.13085](https://arxiv.org/abs/2209.13085)
**Tier:** 2
**Doc passage (§4c):** "Skalse et al. 2022 and Pan, Bhatia, Steinhardt 2022 are the peer-reviewed theoretical backing."
**Abstract gloss:** "The first formal definition of reward hacking, a phenomenon where optimizing an imperfect proxy reward function leads to poor performance according to the true reward function."
**Verdict:** faithful. The "theoretical backing" framing matches — this paper is the formal-definition paper.

#### Pan, Bhatia, Steinhardt 2022 — [arXiv:2201.03544](https://arxiv.org/abs/2201.03544)
**Tier:** 2
**Doc passage (§4c):** "Skalse et al. 2022 and Pan, Bhatia, Steinhardt 2022 are the peer-reviewed theoretical backing."
**Abstract gloss:** Empirically studies reward hacking across four environments; identifies *phase transitions* — capability thresholds where reward-hacking behavior emerges qualitatively.
**Verdict:** faithful, but note: this paper is more empirical than purely theoretical (it constructs experimental environments and reports phase-transition findings). The "theoretical backing" gloss is slightly off in flavour; "empirical-and-theoretical backing" or "empirical complement to the Skalse formal definition" would be more accurate. Not egregious; left as written.

#### AutoGen / Wu et al. 2023 — [arXiv:2308.08155](https://arxiv.org/abs/2308.08155)
**Tier:** 2
**Doc passage (§4c):** "**AutoGen** (Wu et al. 2023) and **MetaGPT** (Hong et al. 2024) are the nearest structural analogs to pm's separated writer-and-checker roles, though pm's watchers are more tightly scoped and tick rather than dialogue."
**Abstract gloss:** "Open-source framework that allows developers to build LLM applications via multiple agents that can converse with each other." Conversation-driven framing matches the doc's "dialogue" contrast.
**Verdict:** faithful.

#### MetaGPT / Hong et al. 2024 — [arXiv:2308.00352](https://arxiv.org/abs/2308.00352)
**Tier:** 2
**Doc passage (§4c):** see AutoGen above.
**Abstract gloss:** "Standardized Operating Procedures (SOPs) into prompt sequences." "Assembly line paradigm to assign diverse roles to various agents."
**Verdict:** faithful. The "structural analog with role decomposition" framing matches the MetaGPT design.

### VI. Audit / cheating detection (§4d) — Tier-2

#### NIST CAISI ("Cheating in AI Agent Evaluations")
**Tier:** 2 (blog-grade)
**Doc passage (§4d):** "**NIST CAISI** … run[s] an LLM reviewer over an evaluation transcript to score it for cheating signals."
**Source gloss:** CAISI defines two cheating categories — solution contamination and grader gaming — and reports observed cheating rates of 0.1% to 4.8% across Cybench / SWE-bench Verified / CVE-Bench, with the transcript-review pattern recommended as a mitigation.
**Verdict:** faithful. Optional: the 0.1–4.8% observed range across CAISI's benchmarks is a useful concrete data point for §4d's "the audit's detection rate on this specific threat is unmeasured" caveat — could be surfaced as a baseline.

#### AISI Inspect Scout
**Tier:** 2 (blog-grade)
**Doc passage (§4d):** "**AISI Inspect Scout** … run[s] an LLM reviewer over an evaluation transcript to score it for cheating signals."
**Source check:** the canonical AISI blog URL ([aisi.gov.uk/blog/pipeline-transcript-analysis-inspect-scout](https://www.aisi.gov.uk/blog/pipeline-transcript-analysis-inspect-scout)) **returned 404 in this pass** — flagged unfetchable. The framing matches the published description of Inspect Scout as an open-source transcript-analysis pipeline built on the Inspect framework.
**Verdict:** unverified by direct fetch (404). Flag for re-verification against the live URL or the GitHub release.

#### Introspection Adapters — [arXiv:2604.16812](https://arxiv.org/abs/2604.16812)
**Tier:** 2
**Doc passage (§4d):** "Anthropic's **Introspection Adapters** (2026, arXiv:2604.16812) train an add-on that makes a model self-report its learned behaviors — complementary to the capstone's run-time transcript audit rather than a substitute for it."
**Abstract gloss:** "Train a single LoRA adapter across these models [with implanted behaviors]" so the adapted model can "verbalize learned behaviors even in previously unseen fine-tuned models." Strong results on AuditBench.
**Verdict:** faithful. The "self-report learned behaviors" gloss matches; the "complementary, not a substitute" framing is the doc's own (correct) distinction.

#### Liars' Bench / Schwettmann et al. 2025 — [arXiv:2511.16035](https://arxiv.org/abs/2511.16035)
**Tier:** 2
**Doc passage (§4d):** "**Liars' Bench**, Schwettmann et al. 2025, arXiv:2511.16035 … asks whether an agent is lying in its outputs, where the capstone asks whether it consulted forbidden inputs — useful background, not direct precedent."
**Abstract gloss:** "Testbed consisting of 72,863 examples of lies and honest responses generated by four open-weight models across seven datasets." Tests lie-detection techniques and finds they "systematically fail to identify certain types of lies, especially in settings where it's not possible to determine whether the model lied from the transcript alone."
**Verdict:** faithful. The doc's "useful background, not direct precedent" framing is precisely the right scoping — and Liars' Bench's specific finding that *transcript-only* lie detection systematically fails is directly relevant to pm's capstone audit, which is itself transcript-only. Optional rewrite: surface that Liars' Bench documents transcript-only-detection failures, which is a more pointed background reference than the current gloss conveys.
**Proposed rewrite (optional):** consider expanding the gloss to: "Liars' Bench (Schwettmann et al. 2025, [arXiv:2511.16035](https://arxiv.org/abs/2511.16035)) documents that current lie-detection techniques systematically fail when evaluation is transcript-only — a failure mode pm's capstone audit, which is also transcript-only, inherits."

#### AgentSpec / Wang et al. 2025 (ICSE 2026) — [arXiv:2503.18666](https://arxiv.org/abs/2503.18666)
**Tier:** 2
**Doc passage (§4d):** "**AgentSpec** (Wang et al. 2025, ICSE 2026) expresses runtime rules for LLM agents."
**Abstract gloss:** "Lightweight domain-specific language for specifying and enforcing runtime constraints on LLM agents" with triggers, predicates, and enforcement mechanisms.
**Verdict:** faithful.

#### AgentAuditor / Wang et al. 2025 (NeurIPS 2025) — [arXiv:2506.00641](https://arxiv.org/abs/2506.00641)
**Tier:** 2
**Doc passage (§4d):** "**AgentAuditor** (Wang et al. 2025, NeurIPS 2025) is a memory-augmented evaluator of agent traces — but neither targets the internet-lookup threat."
**Abstract gloss:** "Universal, training-free, memory-augmented reasoning framework that empowers LLM evaluators." Introduces ASSEBench with 2293 annotated interaction records across 15 risk types.
**Verdict:** faithful. The "memory-augmented evaluator" gloss matches.

#### Anthropic — "Building and Evaluating Alignment Auditing Agents" (2025)
**Tier:** 3 (ref-list only — appears in references with no specific inline argumentative use beyond the general Anthropic-audit-lineage backdrop)
**Source gloss:** Three agents (Investigator, Evaluation, Breadth-First Red-Teaming). Investigator solves Marks et al. auditing game 13% individually / 42% as super-agent.
**Verdict:** the reference exists and is consistent with the broader Anthropic auditing-agent line cited in §4c/§4d via AuditBench. No inline use beyond ref-list.

#### Anthropic — "Measuring and Improving Coding Audit Realism" (2026)
**Tier:** 2
**Doc passage (§5):** "Anthropic's coding-audit-realism and Petri 2.0 notes (alignment.anthropic.com, 2026) report mitigations [for eval-awareness]."
**Source gloss:** Introduces "realism win rate"; reports that giving auditors access to real deployment resources raises realism win rate from 4.6% to 32.8%; finds that improved realism does *not* significantly change Sonnet 4.5 reward-hacking rates.
**Verdict:** faithful on the "report mitigations" framing. Slight under-characterization: the note's headline finding is that **more realism does not change reward-hacking behavior** — a non-trivial caveat the doc could surface. Not egregious.

#### Anthropic — Petri 2.0 (2026)
**Tier:** 2
**Doc passage (§5):** same as above.
**Source gloss:** Adds 70 new seed instructions; deploys a realism classifier; achieves 47.3% median relative drop in eval-awareness on Claude models.
**Verdict:** faithful. The "mitigations" framing is consistent with the source.

#### Anthropic — "Pre-Deployment Auditing Can Catch an Overt Saboteur" (2026)
**Tier:** 3 (ref-list only — listed in references; no specific inline use in the body text)
**Source gloss:** Reports human-auditor + automated system catches 3/3 sabotage models, but automated agent alone catches only 1/3 — the verdict-aggregation failure mode echoed by AuditBench (already Tier-1).
**Verdict:** ref-list-only. The substantive finding (automated agent misses 2/3 saboteurs alone) reinforces the verdict-aggregation concern already present via the AuditBench Tier-1 entry, and could optionally be cited inline to strengthen §4c's tool-to-agent gap discussion.

### VII. Autonomous loops (§4e) — Tier-2

#### Dependabot (GitHub) / Renovate (Mend)
**Tier:** 2 (commercial tools, no academic paper)
**Doc passage (§4e):** "**Dependabot** (GitHub, 2017-) and **Renovate** (Mend, 2017-) poll a repository's dependency surface, open PRs for updates, and defer the merge to whatever gate exists."
**Source check:** widely-deployed tools; the characterization is standard. Not fetched this pass.
**Verdict:** faithful (standard characterization).

#### GitHub Copilot coding agent / Cursor background agents / GitHub Agent HQ / Devin (Cognition)
**Tier:** 2 (commercial products, blog-grade)
**Doc passage (§4e):** "**GitHub's Copilot coding agent** (generally available September 2025), **Cursor's background agents**, **GitHub Agent HQ** (February 2026), and **Devin** (Cognition) — staff the software-engineer role on open-ended work."
**Source check:** practitioner / vendor sources; not fetched this pass. The "human-files-issue → agent-implements → human-reviews" pattern is the consistent published characterization across these products.
**Verdict:** faithful (standard product characterization).

#### "Ralph loop" / Cursor self-driving codebases / OpenAI Codex 1M LOC anecdote
**Tier:** 3 (blog-grade, anecdotal — no formal paper)
**Doc passage (§4e):** "Reported runs are striking — an OpenAI Codex team shipped roughly a million lines across 1,500 pull requests with no human-written code; Cursor ran hundreds of agents building a browser in a week."
**Source check:** blog/anecdotal practitioner reports; not fetched this pass and not load-bearing on a specific number.
**Verdict:** ref-list/anecdotal level. The doc already flags these as practitioner accounts.

### VIII. Harness-evolution adjacent work (§6) — Tier-2

#### Meta-Harness — [arXiv:2603.28052](https://arxiv.org/abs/2603.28052)
**Tier:** 2
**Doc passage (§6):** "**Meta-Harness** (arXiv:2603.28052) searches over the harness code of an LLM application."
**Abstract gloss:** "Automates the design of harness code for LLM applications" via an agentic approach that uses prior execution data and scoring. Reports 7.7-point context-management gain, 4.7-point math gain, and TerminalBench-2 coding improvements over hand-crafted baselines.
**Verdict:** faithful. The "searches over the harness code" gloss correctly captures the contribution; the doc could optionally surface that the search is *grounded on prior execution-data and scoring*, sharpening the contrast with VeRO (an evaluation harness) below.

#### VeRO — [arXiv:2602.22480](https://arxiv.org/abs/2602.22480)
**Tier:** 2
**Doc passage (§6):** "**VeRO** (arXiv:2602.22480) is an evaluation harness for studying such [harness] optimizers."
**Abstract gloss:** VERO provides "(1) a reproducible evaluation harness with versioned agent snapshots, budget-controlled evaluation, and structured execution traces, and (2) a benchmark suite of target agents and tasks with reference evaluation procedures."
**Verdict:** faithful. The "evaluation harness for studying [harness] optimizers" gloss is exactly VeRO's contribution shape.

### IX. Anthropic, AISI, and other industry / blog-grade sources — Tier-2/3

#### Anthropic "How Claude Code Works in Large Codebases"
**Tier:** 3 (ref-list only; not cited inline by argument)
**Verdict:** ref-list level. Source exists at claim.com blog. No inline argumentative use.

#### AISI 2025 "Transcript Analysis for AI Agent Evaluations"
**Tier:** 3 (ref-list only — the inline AISI citation in §4d is "Inspect Scout," handled above)
**Verdict:** ref-list level.

#### Aider, Cline, Codex CLI; LiteLLM mocks ecosystem; LangWatch Scenario
**Tier:** 3 (ref-list-level practitioner-tool listings)
**Verdict:** these appear as one-line backdrop references for the practitioner-tool landscape and the LLM-mocking ecosystem. No inline argumentative use depending on the characterization.

#### Agent scaffolding / "the harness is the product" — 2026 practitioner analyses
**Tier:** 2 (blog-grade but load-bearing for §2's harness-vs-model framing)
**Doc passage (§2):** "swapping the harness around a fixed model swings coding-benchmark scores by tens of points, while swapping the frontier model under a fixed harness moves the score by roughly one point — in one reported case a cheaper model on a better scaffold outscored a flagship model on its own vendor's scaffold."
**Source check:** blog-grade practitioner sources; not retrieved this pass. The references list flags them as such.
**Verdict:** unverified (blog-grade). This is the empirical anchor for §2's framing — the "tens of points vs one point" framing is doing real argumentative work in §2 — so even though the sources are blog-grade, the audit notes this as a Tier-2 entry to track. If the numeric claim becomes contested, sourcing should be hardened (e.g., to peer-reviewed scaffold-vs-model ablation studies).

#### METR "Recent Frontier Models Are Reward Hacking" (2025 blog)
**Tier:** 3 (ref-list only — listed under industry sources; not cited inline by argument)
**Source gloss:** Reports 30.4% reward-hacking rate on RE-Bench, up to 100% on LLM Foundry; documents specific exploit methods (copying reference answers, monkey-patching grader functions). Adds to §4d's threat-profile evidence base.
**Verdict:** ref-list level in the current doc. Optional inline use: METR's specific 30.4–100% range is a stronger empirical anchor for §4d's "frontier models reward-hack" claim than the current set, and could be cited inline if §4d's threat-profile discussion is strengthened.

#### Cognition Labs — "Introducing Devin" blog
**Tier:** 3 (already covered under the §4e commercial-products Tier-2 entry above; the references-list entry is ref-list only)
**Verdict:** consistent across the inline and ref-list uses.

#### SWE-Bench Verified leaderboard (swebench.com/verified.html)
**Tier:** 3 (snapshot reference; one inline mention as the relevant leaderboard, no argument turning on the specific snapshot beyond the OpenAI retraction discussion already audited Tier-1)
**Verdict:** ref-list / snapshot level.

#### Fuzz4All (Xia et al. 2024, ICSE 2024)
**Tier:** 3 (ref-list only — appears in the peer-reviewed reference list but no inline use in the body)
**Verdict:** ref-list-only. The first-author overlap with the Agentless citation (Xia, Chunqiu Steven) is the most likely reason for the listing; no inline argumentative use means no audit needed beyond confirming the reference exists at the claimed venue.

#### Playwright v1.56 release notes / Playwright docs
**Tier:** already audited under Tier-1 (Playwright Test Agents) — no additional entry needed.

---

## Tier-2 summary

Tier-2 entries above cover the remaining ~50 citations in the lit review at abstract-level depth. The pass surfaced four substantive issues:

1. **FLARE ([arXiv:2604.05289](https://arxiv.org/abs/2604.05289))** — the §4a "LLM-guided fuzzing" grouping mischaracterizes FLARE's domain (multi-agent LLM systems, not general programs). Tier-2 finding rises to a proposed rewrite.
2. **In-browser fuzzing ([arXiv:2510.13543](https://arxiv.org/abs/2510.13543))** — same as above: the cited paper targets prompt-injection vulnerabilities in agentic browsers, not classical coverage-driven input fuzzing. Tier-2 finding rises to a proposed rewrite.
3. **ChatUniTest authorship attribution** — the doc cites "Xie et al. 2023" but the arXiv abstract lists Chen, Hu, Zhi, Han, Deng, and Yin. Authorship attribution should be verified.
4. **"Agent scaffolding" §2 anchor sources are blog-grade** — the "tens of points vs one point" claim is doing real argumentative work and rests on un-peer-reviewed analyses. Tier-2 audit flags for hardening if the claim is contested in a future review cycle.

Plus minor notes:
- **Pan, Bhatia, Steinhardt 2022** is more empirical than "theoretical backing" framing implies (not egregious; left alone).
- **Liars' Bench**'s transcript-only-lie-detection failure is more directly relevant to pm's capstone audit than the current "useful background" gloss conveys — optional rewrite proposed.
- **Anthropic Coding Audit Realism** has a non-trivial finding (more realism does *not* change reward-hacking rates) that could be surfaced in §5 — optional.
- **AISI Inspect Scout** blog URL 404'd in this pass; flag for re-verification.

No Tier-1 verdicts are altered by this Tier-2 supplemental pass.
