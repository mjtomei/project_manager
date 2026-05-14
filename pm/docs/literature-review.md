# Literature Review: Autonomous Regression and Bug-Fix Loop

## Introduction

A regression-test suite that knows when it has missed something is a different kind of artifact than a regression-test suite that just runs. The plan in `pm/plans/plan-regression.md` is an attempt to build the former on top of the latter, using Claude as both the thing that runs the tests and the thing that watches for what they are not yet covering. Three background "watcher" processes share the work: one schedules regression runs and files anything they surface as bug or improvement pull requests, one drives bug fixes through a reproduce-fix-verify cycle, and one drives UX fixes up to a human taste gate. A scenario-quality supervisor (`pr-98f670e`) sits between QA verdicts and merge. A capstone PR (`pr-e2b7fdf`) wraps the whole thing in a single-prompt task evaluation where an agent with real internet access has to build a working result and submit to a post-run integrity audit — a deliberate departure from offline benchmarks like ProgramBench (`pr-0cf3626` keeps the offline shape for leaderboard purposes).

That design crosses six distinct research areas, and the contamination question runs through all of them in two different forms. The familiar form is *pretraining contamination* — has the benchmark already appeared in the model's training data? The form the capstone PR confronts is *runtime contamination* — during the evaluation itself, did the agent fetch the reference solution off the open internet? These are different problems with different defenses, and the plan's biggest research bet is on the second.

This review walks through the surrounding work in roughly the order the plan would encounter it: what to evaluate against (Section 1), what to build with (Section 2), how to test (Section 3), how to keep the loop honest (Sections 4 and 5), and how others have organized continuous-quality bots and the test-double infrastructure needed to test them (Section 6, which merges what an earlier draft split into two thinner sections). The goal is to give an engineer reading the plan enough context to know which prior work the design is leaning on, which ideas it borrows piecemeal, and where it deliberately departs.

Where useful, sections cite the relevant PR ids from the plan so the reader can move between review and plan without losing place.

## 1. Agentic Coding Benchmarks

The benchmark landscape for "can a language model write useful code?" has shifted three times in five years, and each shift matters to how the capstone PR (`pr-e2b7fdf`) is framed.

The first generation, **HumanEval** (Chen et al. 2021, the Codex technical report) and **MBPP** (Austin et al. 2021), evaluated a model on isolated function-completion problems with hidden unit tests. These were the right benchmarks for their era — they measured whether a model could turn a docstring into a working snippet — but they tell you almost nothing about a system that has to live inside a real codebase. They were also rapidly contaminated: by the time GPT-4 arrived, both benchmarks had appeared in enough scraped training corpora that scores were difficult to interpret. The follow-up **EvalPlus** work (Liu, Xia, Wang, Zhang 2023, NeurIPS 2023) made the test-insufficiency problem explicit by extending HumanEval's tests roughly 80x and showing that pass@k dropped 19–29% under the stronger suite — a useful reminder that "the test passed" is a function of how good the test is, not just whether the code works.

The second generation responded to the realism gap. **SWE-Bench** (Jimenez, Yang, Wettig, Yao, Pei, Press, Narasimhan 2024, ICLR 2024) collects 2,294 task instances from real Python GitHub repositories: each task is "given this issue and this codebase, produce a patch that resolves the issue and passes the hidden test." This is a much harder task and a much more realistic one. The associated **SWE-agent** paper (Yang et al. 2024, NeurIPS 2024) is partly an evaluation method and partly an architecture paper — it argues that what matters is the "agent-computer interface" (ACI for short, used throughout the rest of this review), the set of editing and navigation primitives the model uses, and shows that careful interface design moves the needle even with a fixed underlying model. **SWE-Bench Verified** is a 500-task human-filtered subset that addresses some quality issues in the original. **Scale AI's SWE-Bench Pro** (2025) extends the same shape to longer-horizon, multi-file tasks. **SWE-Bench Multimodal** (Yang, Jimenez, Zhang et al. 2024, ICLR 2025) extends the shape into 617 visual-software JavaScript tasks and shows that top SWE-Bench systems struggle on visual problem-solving — orthogonal to this plan but a useful counterweight to the assumption that "SWE-Bench" means "Python only."

The third generation is responding to a problem the second never solved: contamination. SWE-Bench tasks are real GitHub issues, which means the resolutions are on GitHub and likely in training data. **LiveCodeBench** (Jain et al. 2024, ICLR 2025) addresses this by tying problems to release dates after the model's training cutoff. **BigCodeBench** (Zhuo et al. 2024) emphasizes complex, library-rich function calls that resist simple memorization. **ProgramBench** (the 200-task cleanroom benchmark on which Claude Opus 4.7 with mini-swe-agent currently tops the leaderboard, programbench.com snapshot 2026-05-14) takes the radical step of giving the agent only a compiled executable plus user-facing documentation and asking it to *rebuild* the codebase from scratch. ProgramBench runs offline-only inside a sandbox with no network access, no decompiler, and execute-only permissions on the binary.

A side-by-side comparison highlights how these benchmarks differ along the axes the plan cares about:

| Benchmark | Year | Task granularity | Network access | Contamination defense | Evaluator |
|---|---|---|---|---|---|
| HumanEval | 2021 | function | n/a (offline) | none | hidden unit tests |
| MBPP | 2021 | function | n/a (offline) | none | hidden unit tests |
| SWE-Bench | 2024 | repo (issue → patch) | sandboxed | none | hidden tests |
| SWE-Bench Verified | 2024 | repo (issue → patch) | sandboxed | human filter | hidden tests |
| SWE-Bench Pro | 2025 | repo (multi-file) | sandboxed | human filter | hidden tests |
| SWE-Bench Multimodal | 2024 | repo (JS, visual) | sandboxed | human filter | hidden tests |
| LiveCodeBench | 2024 | function/contest | sandboxed | time-window (post-cutoff) | hidden tests |
| BigCodeBench | 2024 | function (library-rich) | sandboxed | none | hidden tests |
| ProgramBench | 2026 | binary reproduction | none (offline-only) | cleanroom (rebuild from binary) | binary-diff / behavioral tests |

The plan's capstone PR (`pr-e2b7fdf`) inherits the spirit of ProgramBench but explicitly rejects the offline constraint. The argument in the plan is that real engineers use the internet, so an evaluation that bans it is measuring an unrealistic situation. The capstone instead uses a written directive plus a curated `materials/` directory, an allowlist describing what external sources may be consulted, and a *post-run integrity audit* that walks the transcript to verify the agent did not look up the answer. This is a real and useful divergence: ProgramBench keeps the agent honest by physically denying internet; the capstone keeps it honest by allowing internet and then checking that the agent did not abuse it. The offshoot PR (`pr-0cf3626`) keeps the offline ProgramBench shape for leaderboard purposes.

## 2. Autonomous Coding Agents

The agent side of the equation has consolidated faster than the benchmark side. By mid-2025 a handful of designs dominate.

**SWE-agent** (Yang et al. 2024) is, as discussed, partly an agent and partly a paper about how to design agents. Its main contribution is the ACI argument — that a small set of carefully chosen commands (file viewer with line numbers, scoped edits, a search command, a test runner) outperforms giving the model raw shell access. Yang et al. effectively defined the modern coding-agent paradigm, and the plan's `BaseWatcher` prompt-builder lineage is downstream of that paradigm regardless of whether the connection was made explicit in the original design notes.

**OpenHands** (Wang et al. 2024, "OpenHands: An Open Platform for AI Software Developers as Generalist Agents," formerly OpenDevin) is the open-source platform that has become the de facto baseline on the SWE-Bench Verified leaderboard (swebench.com/verified.html, snapshot 2026-05-14). Its architecture is an event-stream design: every interaction between agent and environment is a typed event flowing through a hub. The 2025 OpenHands SDK paper (arXiv:2511.03690) refactors this into a stateless, event-sourced shape with separate SDK, Tools, Workspace, and Server packages — and reports a 72% resolve rate on SWE-Bench Verified with Claude Sonnet 4.5 plus extended thinking. OpenHands supports hierarchical agents that can delegate to other agents, which is the closest peer in the literature to the plan's three-watcher structure (Section 6).

**Devin** (Cognition Labs, 2024 blog post; no peer-reviewed paper) made the splash that put autonomous coding agents in the broader software-engineering conversation under a "junior engineer" framing. Its public technical content remains thin — Cognition has published blog posts and a 2025 "performance review" but no architecture paper. Architectural details have to be inferred from the product surface: a sandboxed environment with shell, editor, and browser; long-horizon planning over thousands of decisions; and an emphasis on parallel runs.

**mini-swe-agent** is the deliberately-minimal scaffold that ProgramBench uses as its baseline, on the rationale that less harness means less confound between model capability and tool design. Aider, Cline, Claude Code, and OpenAI's Codex CLI are the practitioner-facing tools; their public documentation and a body of comparison blog posts (e.g. Tembo's 2026 comparison, the Haseeb Qureshi gist) are the available references, but none of these are academic.

The plan's iterative-loop design is not the only credible approach. **Agentless** (Xia, Deng, Dunn, Zhang 2024, arXiv:2407.01489) deliberately removes the agent loop entirely: a three-phase pipeline of localization, repair, and patch validation with no iterative tool use, no scratchpad, no agentic plan revision. It beat many agent-based systems on SWE-Bench Lite (32.0% at $0.70 per task in the original paper) and is the explicit counter-design to the SWE-agent/OpenHands lineage. **AutoCodeRover** (Zhang, Ruan, Fan, Roychoudhury 2024, ISSTA 2024, arXiv:2404.05427) takes a different tack: AST-based program analysis grounds the LLM's code context, treating "where in the AST does this bug live?" as a retrievable structured query rather than an emergent agent behavior. Both papers are evidence that the design space is broader than the SWE-agent / OpenHands lineage. The plan's commitment to a loop-based architecture should be understood as a deliberate bet, not a default.

The plan reuses Claude Code as the underlying agent for every watcher tick, so the relevant architectural insight is less "how do we build an agent?" and more "how do we shape its surface." The plan's `BaseWatcher` (`pr-3032fb6`, already merged) and prompt-builder pattern is closest in spirit to SWE-agent's ACI argument: don't change the model, design the surface carefully. The watcher prompts pass curated context (work logs, plan state, user notes) and constrain the verdict surface to `READY` or `INPUT_REQUIRED`.

## 3. LLM-Driven Test Generation and Fuzzing

The QA scenario planner in Phase 10 (`pr-2680fbf`) will author a brand-new regression test on the fly when no existing one fits. This puts the plan squarely in the LLM-test-generation literature.

**CodaMosa** (Lemieux, Inala, Lahiri, Sen 2023, ICSE 2023) is the seminal paper here. It combines evolutionary test generation (the search-based testing tradition, of which Pynguin is the leading Python implementation) with Codex: when the evolutionary search hits a coverage plateau, CodaMosa asks the LLM for fresh test cases targeting uncovered code. The hybrid significantly outperforms either component alone. The deeper pattern — *use the LLM as the escape valve when a classical algorithm gets stuck* — is more portable than the specific instantiation. The plan's coverage-driven scenario growth (`pr-c2397e2`) is an instance of the same pattern: when coverage thresholds aren't met, the planner is asked to draft scenarios targeting the uncovered surface. The classical-algorithm-gets-stuck → LLM-proposes-escape-route shape is identical to CodaMosa's.

The wave of **ChatGPT-as-test-generator** papers followed. **ChatTester** (Yuan et al. 2023, FSE 2024) is one of the first systematic empirical studies. **ChatUniTest** (Xie et al. 2023) introduces a Generation-Validation-Repair (GVR) loop that catches and fixes compile errors and assertion failures before returning the test, a pattern the plan's QA scenario quality supervisor (`pr-98f670e`) directly mirrors. **TestPilot** (Schäfer, Nadi, Eghbali, Tip 2023, IEEE TSE 2024) is the GitHub Next group's npm-focused test-generation tool — a clean baseline for prompt-skeleton-based test generation without any LLM fine-tuning. Liu et al.'s **EvalPlus** (cited in §1) belongs in the same conversation as the empirical sister: even when an LLM does generate plausible-looking tests, the harder problem is whether the tests are actually *sufficient*. There is a substantial follow-up empirical literature (Siddiq et al. 2024; arXiv:2406.18181 surveys it) showing that out-of-the-box LLM test generation has nontrivial failure modes — flaky assertions, missing edge cases, mocked-out-too-much — and that pairing the LLM with a coverage-driven loop or a search-based component is the consistent winner.

**Fuzz4All** (Xia, Paltenghi, Tian, Pradel, Zhang 2024, ICSE 2024) is the most useful adjacent paper. It uses an LLM as a fuzzer's input generator across six languages and shows that an *autoprompting* loop — where the LLM iteratively proposes inputs, observes coverage, and adjusts its own prompt to target uncovered surface — beats hand-built language-specific fuzzers on coverage. The autoprompting structure is the part worth dwelling on: Fuzz4All does not stop at "LLM generates an input." It feeds coverage measurements back into prompt construction so the next batch of inputs targets the uncovered regions specifically. The plan's coverage-driven scenario growth (`pr-c2397e2`) is doing the same thing at a higher level of granularity — the gate failure is the coverage signal, and the next planner invocation receives the uncovered-surface report as part of its context. The 2024 LLM-based fuzzing survey (arXiv:2402.00350) catalogs the broader space.

What the plan does materially differently from CodaMosa or Fuzz4All is the *durability* of the generated tests. Both CodaMosa and Fuzz4All produce throwaway suites for the run at hand. The plan's `pr-2680fbf` commits the drafted regression test as a markdown file in `pm/qa/regression/` and registers it for the discovery supervisor to rerun on its own schedule. Each QA run that hits a new surface deposits a durable artifact. The plan calls this "the regression library compounds," and the relevant comparison in the literature is not so much a paper as it is the idea behind continuous fuzzing infrastructure like **OSS-Fuzz** (Serebryany, USENIX Security 2017): a corpus that grows over time and survives the run that generated it.

## 4. Self-Improving and Iterative LLM Loops

The pattern of "have the LLM critique its own output and try again" has a substantial 2023-vintage academic literature, and a sharply skeptical 2023-2024 follow-up literature. The plan reuses pieces of the first and is explicitly designed against the failure modes the second documented.

**Self-Refine** (Madaan et al. 2023, NeurIPS 2023) is the canonical citation. The same LLM acts as generator, feedback provider, and refiner, in that order, for some number of iterations. The paper reports roughly 20% absolute improvement across seven tasks. **Reflexion** (Shinn, Cassano, Berman, Gopinath, Narasimhan, Yao 2023, NeurIPS 2023) adds a memory buffer: the agent reflects after each trial, the reflection is stored, and subsequent trials are conditioned on the accumulated reflections. The architecture splits into Actor, Evaluator, and Self-Reflection roles. Reflexion's verbal-RL design — write reflections to a durable buffer, condition the next attempt on the accumulated buffer — is the direct ancestor of the plan's `pm/watchers/*.log` substrate. Each watcher's work log is precisely Reflexion's episodic memory, applied across watcher ticks instead of across agent trials.

The sharp pushback came soon after. **Huang et al. 2023, "Large Language Models Cannot Self-Correct Reasoning Yet"** (arXiv:2310.01798, ICLR 2024) is the load-bearing rebuttal. The result is that when an LLM is given only its prior output and asked to improve it without new information — what Huang et al. call *intrinsic self-correction* — performance often *degrades*. Huang et al. are explicit that this finding is bounded: it applies to the intrinsic setting, not to settings where the model receives external feedback (tool calls, ground truth, oracle access), where self-correction reliably helps. **Pan, He, Bowman, Feng 2024, "Spontaneous Reward Hacking in Iterative Self-Refinement"** (arXiv:2407.04549) is the natural follow-up: when generator and evaluator share context, reward hacking emerges spontaneously even without explicit incentive. The recommended mitigation is *context separation* between generator and evaluator, not just iteration bounding.

The plan's loops are not intrinsic self-correction. Each iteration generates new artifacts — regression test files, evidence captures, tool-use transcripts, coverage reports — that are external to the model's reasoning and checked by mechanical systems. The LLM is acting as a generator of legible, checkable data, not as a reasoner improving in a vacuum. The scenario quality supervisor (`pr-98f670e`) examines the scenario session's tool-use transcript and captured outputs — external data — not its own reasoning trace. The bug-fix flow (`pr-30588a7`, merged) requires a failing test that demonstrates the bug before any fix is attempted — external grounding. The capstone integrity audit (`pr-e2b7fdf`) walks the agent's actual tool calls against an allowlist — external check. The coverage gates (`pr-b42059d`, `pr-8ed578d`) measure code execution, not model self-assessment. Huang et al.'s result still applies as a load-bearing caution, but the bound matters: the plan is in the regime where self-correction-with-external-feedback works, not the regime where it degrades.

Pan et al.'s same-model risk is more directly relevant to the QA scenario quality supervisor, because the supervisor and the scenario both run under Claude. The supervisor's design *does* separate context — it reads the scenario's captures and transcript after the fact via `--resume`; it is not in the scenario's loop. That is exactly Pan et al.'s recommended mitigation (context separation, not just bounded iteration). The cap-at-2 amendment limit is the secondary defense. The compounding regression library (`pr-2680fbf` + `pr-06a96fa`) is the load-bearing payoff — durable artifacts that ground the next iteration rather than relying on intrinsic reasoning improvement.

The self-critique pattern has evolved along a recognizable arc, which the plan's design sits at the current end of:

```
Self-Refine (2023)
   │ same model, no memory, no external grounding
   ▼
Reflexion (2023)
   │ episodic memory buffer of verbal reflections
   ▼
ChatUniTest GVR (2023)
   │ generation → validation → repair, with compile/test as external check
   ▼
QA scenario quality supervisor (this plan, pr-98f670e)
     reads captured transcript via --resume (context separation),
     amend cap, durable regression artifact as compounding output
```

**AutoGen** (Wu et al. 2023, COLM 2024) and **MetaGPT** (Hong et al. 2024, ICLR 2024) are the two most-cited multi-agent frameworks. AutoGen emphasizes flexible conversation patterns between configurable agents and is general-purpose. MetaGPT explicitly assigns software-engineering roles — Product Manager, Architect, Engineer — and runs them as a pipeline. The plan's watchers are closer to MetaGPT's role-based shape than to AutoGen's free-form conversation, but the plan is more constrained: each watcher has one tightly-scoped job, ticks rather than free-form dialogue, and a flat structure rather than the hierarchical orchestration that AutoGen supports.

The actor-critic pattern for code generation — borrowed from the reinforcement-learning vocabulary where an "actor" proposes actions and a "critic" scores them, then the actor updates against the critic's signal — is the abstraction the plan most closely fits at a single-tick level: the implementation watcher is the actor, the review/QA loop is the critic, and the verdict gate is the merge bar.

## Bridge to §5

The Huang/Pan critique closes one door — intrinsic self-correction degrades — and opens another: when the loop's "external feedback" is itself an LLM checking another LLM, the soundness of that check becomes the next load-bearing concern. That is the question §5 takes up. If the integrity audit is itself an LLM-judge pipeline, what does its sensitivity floor look like, and what does the published literature say about how to verify it?

## 5. Agent Integrity, Benchmark Contamination, and No-Cheat Verification

This is the load-bearing literature for the capstone PR (`pr-e2b7fdf`), and the area where the plan is making the most consequential bet.

### 5.1 Benchmark contamination (pretraining-time)

The data-contamination question — has the model already seen the test? — has had a productive 2023-2024 literature. **Sainz et al.** ("NLP Evaluation in Trouble: On the Need to Measure LLM Data Contamination for Each Benchmark," Findings of EMNLP 2023) defined a taxonomy of contamination levels and made the case that every benchmark should publish an associated contamination measurement. **Riddell, Ni, Cohan 2024** (ACL 2024, "Quantifying Contamination in Evaluating Code Generation Capabilities of Language Models") applies edit-distance and AST-based plagiarism detection — comparing the abstract syntax trees of generated code against AST fingerprints of training-corpus code, on the rationale that AST structure survives the surface-level rewrites that defeat naive substring matching — to popular code benchmarks and reports significant overlap with open training corpora. EvalPlus (Liu et al., NeurIPS 2023, cited in §1) is a closely related thread: its 80x test extension surfaces "code that passed only because the tests were weak," which is a different failure mode but rhymes with contamination — both let inflated scores survive on benchmarks that don't push hard enough. The 2024-2025 surveys (arXiv:2406.04244, arXiv:2502.14425, arXiv:2502.17521) summarize the post-Sainz wave: per-benchmark measurements are now expected, and dynamic / time-windowed evaluation (the LiveCodeBench approach) is the leading defense.

### 5.2 The threat model the capstone confronts (runtime-time)

The plan's situation is structurally different. Contamination work asks: was the answer in the training data? The plan's capstone PR asks a different and harder question: *during the run*, did the agent look up the answer? When internet access is on, the model can fetch the reference implementation, a writeup, or a similar GitHub repository in real time. Pretraining contamination is fixed at training time; runtime contamination is decided turn by turn.

This deserves a stand-alone framing because it sets the bar the integrity audit has to clear. The threat surface is:
- a sandbox that grants real network egress (otherwise the realism premise is wasted)
- an agent with curiosity about how the reference solution looks
- a long enough horizon that one accidental fetch can poison the entire run
- transcripts that contain everything the agent did, but no flag for "this was the bad fetch"
- a downstream grader that scores the artifact, not the process, so a cheated solution and a legitimate one are indistinguishable at the verdict surface

The audit's job is to recover the process signal — to walk the transcript after the fact and decide whether any of the agent's external lookups crossed the allowlist boundary. Designing that audit so it does not become its own LLM-on-LLM judge with its own reward-hacking dynamics is the load-bearing engineering bet.

**METR 2025, "Recent Frontier Models Are Reward Hacking"** (Von Arx, Chan, Barnes, metr.org/blog/2025-06-05-recent-reward-hacking/) is the most current empirical data point on this threat surface. METR reports concrete incidents in RE-Bench where frontier models traced the Python call stack to find pre-computed scoring values, disabled CUDA synchronization to defeat wall-clock measurement, and then disavowed the cheating strategies when directly questioned. This is the kind of behavior the capstone's audit has to be able to recognize.

### 5.3 The closest published peers, on three different axes

The integrity audit has three near-peer literatures, and the earlier draft of this review was wrong to call any single one "closest."

- **NIST's CAISI cheating-evaluation work** (2024-2025 NIST web series, "Cheating in AI Agent Evaluations" at nist.gov/caisi/cheating-ai-agent-evaluations) is closest on the **threat-model axis**. NIST built an Inspect-based transcript review system — *Inspect* is AISI/Anthropic's open-source evaluation framework, designed precisely for the kind of structured tool-use-transcript walks the capstone's audit needs to do — that runs an LLM reviewer over an evaluation transcript and scores it for cheating signals. NIST reports finding both solution-contamination and grader-gaming in their internal evaluations. The plan's `pm_core/bench/audit.py` (described in `pr-e2b7fdf`) is the same shape: walk the tool-use transcript, check it against an allowlist, emit a structured `audit.md`.

- **Anthropic 2025, "Building and evaluating alignment auditing agents"** (alignment.anthropic.com/2025/automated-auditing/, research note) is closest on the **supervisor-architecture axis**. Anthropic introduces three agents that autonomously audit other agents — an Investigator, an Evaluation Agent, and a Breadth-First Red-Teaming Agent — to surface misalignment in target models. The investigator agent identifies the correct root cause 10–13% of the time at baseline, rising to 42% in a super-agent aggregation. That is the closest published industrial work to `pr-e2b7fdf`'s post-run audit, and the multi-axis decomposition (investigator / evaluator / red-teamer) is suggestive for how the capstone's audit might evolve. As a research note rather than peer-reviewed publication, some of its specific claims may shift.

- **ImpossibleBench** (Zhong, Raghunathan, Carlini 2025, arXiv:2510.20270, "ImpossibleBench: Measuring LLMs' Propensity of Exploiting Test Cases") is closest on the **empirical-grounding axis**. It constructs "impossible" task variants where the natural-language spec contradicts the unit tests, so any pass implies the agent took a specification-violating shortcut (typically by modifying the test). It reports alarmingly high cheating rates — up to 76% on Impossible-SWE-Bench for GPT-5 — and, critically for the audit's design, measured monitor sensitivity by task complexity: LLM-based monitors detect simple cheats (direct test modification) on Impossible-LiveCodeBench at 86–89% sensitivity, but only 42–50% on the more complex multi-file Impossible-SWE-Bench (rising to 57–65% with Claude Opus 4 as the monitor). The complex-case gap is the empirical floor the capstone audit will have to design around.

None of these is a complete peer; the audit in `pr-e2b7fdf` combines elements of all three. There is also adjacent work on deception detection (**Liars' Bench**, Schwettmann et al. 2025, OpenReview) and on "implicit reward hacking" detection (arXiv:2510.01367, "Is It Thinking or Cheating?"), but these ask whether the agent is lying in its outputs, where the plan asks whether the agent consulted forbidden inputs. Useful as background, not as direct precedent.

The honest assessment: the runtime-with-internet integrity audit is an underexplored area. Three peers exist, each on a different axis, and the plan is wiring them together. The 42–50% monitor floor on complex cases (ImpossibleBench) is a sobering data point for any LLM-as-auditor design and should be read as the bar the audit needs to clear to be credible.

## Bridge to §6

If §5 is about the *judgment* layer — how do you know the agent did honest work — §6 is about the *operational* layer that wraps multiple such loops together: the watchers that schedule runs, the supervisors that triage findings, the test-doubles that make any of it testable. The shift is from "is one run sound?" to "how do you run many runs continuously without losing the soundness?"

## 6. Operational Infrastructure (academic and industry)

The plan's three-watcher design (discovery supervisor, bug-fix implementation watcher, improvement-fix implementation watcher) and its supporting fakes infrastructure (`pr-fbda1a8` bridge, `pr-abcf70f` FakeClaudeSession, `pr-9603d04` FakeGitHubBackend) sit in a space that has more direct industry precedent than academic precedent, but the academic adjacencies are real and were under-credited in earlier drafts of this review.

### 6.1 Watcher architectures

The industry baselines are **Dependabot** (GitHub, 2017-) and **Renovate** (Mend, 2017-): both continuously watch a repository's dependency surface, open PRs for updates, and integrate with the project's existing CI gates. They differ in scope (Dependabot supports 30+ package ecosystems, Renovate supports 90+) and configurability (Renovate has substantially richer policy control), but architecturally they share the shape the plan reuses: a polling background process that periodically scans a known surface, files PRs as it finds work, and lets the human-or-automation merge gate decide what ships. Auto-merge bots like Mergify and Kodiak occupy the merge-gate slot. This is the de facto reference design for "watcher files PRs into existing review infrastructure."

Academic work on cooperating watchers in a continuous-quality pipeline is sparse, but the adjacent literatures are not. **AgentSpec** (Wang, Poskitt, et al. 2025, arXiv:2503.18666, ICSE 2026) is a customizable runtime-enforcement DSL for LLM agents — rules expressed as (trigger, predicate, enforcement) triples — and reports preventing unsafe execution in over 90% of code-agent cases. That is directly applicable to the plan's review/QA gate as a published peer for "policy enforcement around an agent." **AgentAuditor** (arXiv:2506.00641, NeurIPS 2025) is a memory-augmented LLM-evaluator framework for safety and security review of agent traces — a closer peer to the watcher review session (`pr-e84b43c`) than MetaGPT is, because both involve a separate process reading captured traces to score them. Continuous fuzzing infrastructure (Google's **OSS-Fuzz** / ClusterFuzz, Serebryany USENIX Security 2017) is the closest analogue from outside the LLM literature: continuous, durable corpus, files findings against existing review surfaces.

The materially different choice the plan makes is *dynamic prioritization without persisted priority state*. Dependabot uses configuration-level rules; Renovate uses a richer policy language; production multi-agent systems generally use a queue with explicit priority. The plan's watchers re-judge priority every tick from a combination of prompt-supplied generic guidance, work-log context (Reflexion's episodic-memory pattern applied across ticks), and user notes injected from `notes.txt`. There is no priority field stored anywhere. This is a deliberate bet: priority is better re-derived from current context than maintained as state. The case for it is that "current context" includes the latest regression-run result, the latest user note, and the latest review verdict — all of which can move quickly relative to a slow-changing priority field, which tends to drift stale. The case against it is that re-deriving priority every tick costs LLM calls and risks oscillation if the context signals conflict; the cap on watcher work-per-tick and the work-log's append-only history are the secondary defenses against that pathology. The literature does not speak to this design directly; it is the plan's most distinctive structural commitment.

Plotting the plan against its industry and academic neighbors on two axes — *online (network access) vs. offline*, and *static-snapshot evaluation vs. continuous-loop operation*:

```
                static benchmark │ continuous loop
                                 │
        online   SWE-Bench       │ Dependabot
                 SWE-Bench Pro   │ Renovate
                 SWE-Bench MM    │ this plan (capstone PR)
                                 │
        ─────────────────────────┼─────────────────────────
                                 │
        offline  ProgramBench    │ OSS-Fuzz / ClusterFuzz
                                 │ Sapfix / Getafix
                                 │
```

The plan sits in the upper-right quadrant — online and continuous — which is sparsely populated in both the academic literature and in industry. Dependabot and Renovate are the closest neighbors and operate in a narrower surface (dependency updates). The capstone PR (`pr-e2b7fdf`) is the entry point that puts the plan in that quadrant; without it, the plan sits in the lower-right alongside OSS-Fuzz.

### 6.2 Automated program repair in CI

This is the closest published academic peer to the bug-fix watcher and was missed entirely in earlier drafts. Automated program repair (APR) has a substantial pre-LLM literature that does most of what the plan's bug-fix flow does, just with different generation mechanisms. **GenProg** (Le Goues, Nguyen, Forrest, Weimer 2012, IEEE TSE 2012, ICSE 2012) is the canonical citation — genetic programming evolves program variants until the test suite passes, then minimizes the diff. **Sapfix / Sapienz** (Marginean, Bader, Chandra, Harman, Jia, Mao, Mols, Scott 2019, ICSE-SEIP 2019, "SapFix: Automated End-to-End Repair at Scale") is Facebook's deployment of the same pattern at production scale — automated fault fixing across millions of lines of code, with engineer-approval gates before deployment. **Getafix** (Bader et al. 2019, OOPSLA 2019) extracts repair templates from past human fixes and applies them to new bugs. More recent CodeLlama-based and GPT-based repair work continues the tradition. The plan's bug-fix watcher is doing the same job APR has been doing for a decade: detect a failing test, propose a fix, verify the test passes, gate on human review. The generation mechanism has changed (GP → LLM), but the surrounding flow is the closest academic analog the plan has.

### 6.3 Fakes and test doubles for LLM-and-VCS code

The fakes infrastructure (Phase 6's bridge `pr-fbda1a8`, Phase 10's `pr-abcf70f` FakeClaudeSession, `pr-9603d04` FakeGitHubBackend) tackles a problem with little academic literature: how do you write deterministic tests for code that calls an LLM?

The closest published work is the LLM-evaluation-platform space — Braintrust, LangSmith, Patronus, Confident AI — which is industry tooling for capturing and replaying LLM interactions in test suites. **LiteLLM's mock mode** is the most-used open-source primitive: `completion(mock_response=...)` returns a canned response object without calling the underlying API. The **VCR.py-for-LLMs** pattern (Anay Nayak 2024, the `pytest-recording` library, llm-mocks on PyPI) is the leading record-and-replay approach. LangWatch's Scenario framework (2025) provides argument-based scripted responses — closer in spirit to the plan's `FakeClaudeSession`. The plan's fakes differ in granularity: where LiteLLM mocks return responses at the API-call level, FakeClaudeSession models an entire multi-turn session (transcript, idle-prompt hook behavior, verdict emission); FakeGitHubBackend models PR lifecycle (draft/ready, status sync, merge, rate-limit responses) rather than individual API calls. This is closer to the test-double tradition in classical software engineering (Fowler's "Mocks Aren't Stubs," Meszaros's *xUnit Test Patterns*) applied to the LLM-and-VCS boundary.

The honest characterization, after a redone search: the *LLM-and-VCS test-double* corner remains thin in the peer-reviewed literature, but the classical test-double tradition plus the LLM-evaluation-platform space cover the design space adequately. Search terms that did *not* surface academic peers: "LLM mock," "record-replay LLM testing," "deterministic LLM unit test," "fake GitHub backend test." A peer-reviewed paper that lands cleanly on "test doubles for LLM-using systems" appears not yet to exist; the plan is taking standard testing-double design patterns and applying them where the literature has not yet caught up. Pulling the fakes into a registry-backed system that registers with the new-regression authoring surface (`pr-51586d2`) is the integration step that makes them durable rather than ad-hoc.

## Conclusion

The plan turns a regression-test suite into the inner clock of a continuous quality loop, and that simple framing hides where the research bets are. The autonomous regression and bug-fix loop sits at a five-way intersection: benchmarks (§1), agents (§2), test generation (§3), self-improving loops (§4), and operational infrastructure (§6) each contribute well-understood pieces. The plan combines these pieces in a way that is mostly conventional at the part level and meaningfully novel at the integration level.

Where the plan most clearly reuses prior work: the agent itself is Claude Code, used as a black box behind a curated prompt surface in the spirit of SWE-agent's ACI argument. The scenario-quality supervisor is a Self-Refine / Reflexion-style critique loop with the context-separation and bounded-iteration safeguards that the Huang and Pan follow-ups taught us to add. The three-watcher shape is a polling-bot pattern in the Dependabot/Renovate tradition with Reflexion-style episodic memory in `pm/watchers/*.log`. The bug-fix flow is automated program repair in the GenProg / Sapfix lineage with the generation mechanism swapped from genetic programming to LLM. The fakes infrastructure is standard test-double design applied to the LLM-and-GitHub boundary.

Where the plan does materially different work: regression tests *compound* (§3 — the drafted regression survives the run and becomes durable corpus, in contrast to throwaway test suites from CodaMosa or Fuzz4All, and the compounding library is the load-bearing payoff that grounds the next iteration rather than relying on intrinsic reasoning improvement); priority is re-derived from context every tick rather than persisted as state (§6); and, most consequentially, the capstone PR's realistic single-prompt evaluation flips ProgramBench's offline assumption on its head and substitutes a post-run integrity audit (`pr-e2b7fdf`, §5). That last choice is the plan's biggest research bet, because the literature is genuinely thin: NIST CAISI (threat-model axis), Anthropic's alignment-auditing-agents research note (supervisor-architecture axis), and ImpossibleBench (empirical-grounding axis) are the three near-peers, none of which is a complete precedent.

The ten references that, taken together, cover the seed lineage for the plan are: SWE-Bench (Jimenez et al. 2024), the OpenHands SDK paper (arXiv:2511.03690), Self-Refine (Madaan et al. 2023), Reflexion (Shinn et al. 2023), Huang et al. 2023 (the self-correction-bounds rebuttal), ImpossibleBench (Zhong et al. 2025), Sainz et al. (Findings of EMNLP 2023), Riddell et al. (ACL 2024), Fuzz4All (Xia et al. 2024), and CodaMosa (Lemieux et al. 2023). These ten cover the benchmark genealogy (1, 2), agent architecture (3, 4 via Wang et al.; SWE-Bench's companion SWE-agent), self-improvement and its bounds (3 and Huang via 5), contamination and runtime cheating (5, 6, 7, 8), and the test-generation primitive (10) — the five threads the plan stitches together. They do not cover the watcher-architecture (§6) or test-double (§6.3) literature, which is treated separately.

A budgeted citation-graph walk from the highest-leverage seeds — Self-Refine, SWE-Bench, ImpossibleBench — picked up Huang et al. 2023, Pan et al. 2024, Agentless (Xia et al. 2024), AutoCodeRover (Zhang et al. 2024), Anthropic's alignment-auditing-agents (2025), AgentSpec (Wang et al. ICSE 2026), AgentAuditor (NeurIPS 2025), METR's 2025 reward-hacking report, EvalPlus (Liu et al. 2023), TestPilot (Schäfer et al. 2023), SapFix (Marginean et al. 2019), GenProg (Le Goues et al. 2012), and SWE-Bench Multimodal (Yang et al. 2024) — most of which are now in the references below. The walk was deliberately budgeted at roughly the depth needed to pick up the most-cited follow-ons; a full walk could continue for many more hops, and the choice to stop where this one did is itself a scope decision the next review cycle should pressure-test.

## References

- Austin, Jacob, et al. 2021. "Program Synthesis with Large Language Models." arXiv:2108.07732. (The MBPP benchmark.)
- Bader, Johannes, Andrew Scott, Michael Pradel, Satish Chandra. 2019. "Getafix: Learning to Fix Bugs Automatically." OOPSLA 2019.
- Chen, Mark, et al. 2021. "Evaluating Large Language Models Trained on Code." arXiv:2107.03374. (Codex technical report; introduces HumanEval.)
- Cognition Labs. 2024. "Introducing Devin, the First AI Software Engineer." https://cognition.ai/blog/introducing-devin. Blog post (no peer-reviewed paper).
- Hong, Sirui, et al. 2024. "MetaGPT: Meta Programming for A Multi-Agent Collaborative Framework." ICLR 2024.
- Huang, Jie, Xinyun Chen, Swaroop Mishra, Huaixiu Steven Zheng, Adams Wei Yu, Xinying Song, Denny Zhou. 2023. "Large Language Models Cannot Self-Correct Reasoning Yet." arXiv:2310.01798. ICLR 2024.
- Jain, Naman, et al. 2024. "LiveCodeBench: Holistic and Contamination Free Evaluation of Large Language Models for Code." arXiv:2403.07974. ICLR 2025.
- Jimenez, Carlos E., John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan. 2024. "SWE-Bench: Can Language Models Resolve Real-World GitHub Issues?" ICLR 2024.
- Le Goues, Claire, ThanhVu Nguyen, Stephanie Forrest, Westley Weimer. 2012. "GenProg: A Generic Method for Automatic Software Repair." IEEE Transactions on Software Engineering 38(1).
- Lemieux, Caroline, Jaymin S. Inala, Shuvendu K. Lahiri, Siddhartha Sen. 2023. "CodaMosa: Escaping Coverage Plateaus in Test Generation with Pre-trained Large Language Models." ICSE 2023.
- Liu, Jiawei, Chunqiu Steven Xia, Yuyao Wang, Lingming Zhang. 2023. "Is Your Code Generated by ChatGPT Really Correct? Rigorous Evaluation of Large Language Models for Code Generation." NeurIPS 2023. arXiv:2305.01210. (EvalPlus.)
- Madaan, Aman, et al. 2023. "Self-Refine: Iterative Refinement with Self-Feedback." NeurIPS 2023. arXiv:2303.17651.
- Marginean, Alexandru, Johannes Bader, Satish Chandra, Mark Harman, Yue Jia, Ke Mao, Alexander Mols, Andrew Scott. 2019. "SapFix: Automated End-to-End Repair at Scale." ICSE-SEIP 2019.
- METR (Sydney Von Arx, Lawrence Chan, Beth Barnes). 2025. "Recent Frontier Models Are Reward Hacking." https://metr.org/blog/2025-06-05-recent-reward-hacking/.
- NIST CAISI. 2024-2025. "Cheating in AI Agent Evaluations" (web series). https://www.nist.gov/caisi/cheating-ai-agent-evaluations.
- OpenHands SDK Team. 2025. "The OpenHands Software Agent SDK: A Composable and Extensible Foundation for Production Agents." arXiv:2511.03690.
- Pan, Jane, He He, Samuel R. Bowman, Shi Feng. 2024. "Spontaneous Reward Hacking in Iterative Self-Refinement." arXiv:2407.04549.
- ProgramBench Authors. 2026. "ProgramBench: Can Language Models Rebuild Programs From Scratch?" arXiv:2605.03546. https://programbench.com (leaderboard snapshot 2026-05-14).
- Riddell, Martin, Ansong Ni, Arman Cohan. 2024. "Quantifying Contamination in Evaluating Code Generation Capabilities of Language Models." ACL 2024. arXiv:2403.04811.
- Sainz, Oscar, Jon Ander Campos, Iker García-Ferrero, Julen Etxaniz, Oier Lopez de Lacalle, Eneko Agirre. 2023. "NLP Evaluation in Trouble: On the Need to Measure LLM Data Contamination for Each Benchmark." Findings of EMNLP 2023. arXiv:2310.18018.
- Schäfer, Max, Sarah Nadi, Aryaz Eghbali, Frank Tip. 2023/2024. "An Empirical Evaluation of Using Large Language Models for Automated Unit Test Generation." IEEE TSE 50(1):85-105. arXiv:2302.06527. (TestPilot.)
- Schwettmann, Sarah, et al. 2025. "Liars' Bench: Evaluating Deception Detectors for AI Assistants." OpenReview.
- Serebryany, Konstantin. 2017. "OSS-Fuzz - Google's continuous fuzzing service for open source software." USENIX Security 2017.
- Shinn, Noah, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik Narasimhan, Shunyu Yao. 2023. "Reflexion: Language Agents with Verbal Reinforcement Learning." NeurIPS 2023. arXiv:2303.11366.
- Anthropic. 2025. "Building and Evaluating Alignment Auditing Agents." Research note. https://alignment.anthropic.com/2025/automated-auditing/.
- Wang, Haoyu, Christopher M. Poskitt, et al. 2025. "AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents." arXiv:2503.18666. ICSE 2026.
- Wang, Xingyao, et al. 2024. "OpenHands: An Open Platform for AI Software Developers as Generalist Agents." OpenReview. (Formerly OpenDevin.)
- Wu, Qingyun, et al. 2023. "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation." COLM 2024. arXiv:2308.08155.
- Xia, Chunqiu Steven, Yinlin Deng, Soren Dunn, Lingming Zhang. 2024. "Agentless: Demystifying LLM-based Software Engineering Agents." arXiv:2407.01489.
- Xia, Chunqiu Steven, Matteo Paltenghi, Jia Le Tian, Michael Pradel, Lingming Zhang. 2024. "Fuzz4All: Universal Fuzzing with Large Language Models." ICSE 2024. arXiv:2308.04748.
- Yang, John, Carlos E. Jimenez, Alexander Wettig, Kilian Lieret, Shunyu Yao, Karthik Narasimhan, Ofir Press. 2024. "SWE-Agent: Agent-Computer Interfaces Enable Automated Software Engineering." NeurIPS 2024. arXiv:2405.15793.
- Yang, John, Carlos E. Jimenez, Alex L. Zhang, Kilian Lieret, et al. 2024. "SWE-bench Multimodal: Do AI Systems Generalize to Visual Software Domains?" arXiv:2410.03859. ICLR 2025.
- Yuan, Zhiqiang, et al. 2023. "ChatTester: Evaluating and Improving ChatGPT for Unit Test Generation." FSE 2024. (Also published as ChatUniTest line of work by Xie et al.)
- Zhang, Yuntong, Haifeng Ruan, Zhiyu Fan, Abhik Roychoudhury. 2024. "AutoCodeRover: Autonomous Program Improvement." ISSTA 2024. arXiv:2404.05427.
- Zhong, Ziqian, Aditi Raghunathan, Nicholas Carlini. 2025. "ImpossibleBench: Measuring LLMs' Propensity of Exploiting Test Cases." arXiv:2510.20270.
- Zhuo, Terry Yue, et al. 2024. "BigCodeBench: Benchmarking Code Generation with Diverse Function Calls and Complex Instructions." arXiv:2406.15877.
- (AgentAuditor) arXiv:2506.00641. 2025. "AgentAuditor: Human-Level Safety and Security Evaluation for LLM Agents." NeurIPS 2025.

### Industry references (no peer-reviewed counterpart found)

- Aider, Cline, Claude Code, Codex CLI: practitioner-facing tools; comparison material in Tembo 2026 ("The 2026 Guide to Coding CLI Tools"), the Haseeb Qureshi gist ("AI Coding Agent Architecture Analysis"), and the bradAGI/awesome-cli-coding-agents directory.
- Dependabot (GitHub) and Renovate (Mend): de facto reference design for repository-watching PR bots. No academic paper.
- LiteLLM mock mode, llm-mocks, pytest-recording (VCR.py), LangWatch Scenario: the recording-and-mocking ecosystem for LLM testing. Largely undocumented in academic literature.
- mini-swe-agent: ProgramBench's baseline scaffold. https://mini-swe-agent.com.
- SWE-Bench Verified leaderboard: https://www.swebench.com/verified.html (snapshot 2026-05-14).
