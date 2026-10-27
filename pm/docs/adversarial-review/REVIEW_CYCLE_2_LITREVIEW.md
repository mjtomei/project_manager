# Review Cycle 2 — Literature Review (`pm/docs/literature-review.md`)

Reviewer: fresh Claude session, blind to Cycle 1. Cycle 2 is required by the methodology to be harder than Cycle 1. Block 3 is load-bearing for this artifact: its stated audience is a non-developer evaluating whether to use `pm`.

---

## Block 1 — Substance

### 1.1 The three-axes framing in §5.3 is its own form of overstatement.

The review claims "NIST closest on threat model, Anthropic on supervisor architecture, ImpossibleBench on empirical grounding." This framing is rhetorically tidy but does not survive scrutiny:

- **NIST CAISI** is not just close on threat model — it is, by the review's own description, the same shape as the audit (`pm_core/bench/audit.py`): walk a transcript, check against an allowlist, emit a structured artifact. That is architectural *and* threat-model overlap. Calling it "threat-model only" understates the precedent and lets the review hold onto a "we're integrating three thin peers" novelty claim that doesn't hold once you notice NIST already integrated at least two of those axes.

- **ImpossibleBench** is positioned as the "empirical grounding" peer, but the cited 42-50% / 86-89% / 57-65% numbers are detection sensitivities for *test modification* (the agent rewrites the unit tests). The capstone's audit is for *external lookup* (the agent fetches the reference solution off the internet). These are different threats with different detection signatures. Borrowing ImpossibleBench's monitor-sensitivity floor as "the bar the capstone audit must clear" is a category error — the audit isn't even reading the same kind of signal. The review should either drop the "empirical floor" framing or argue explicitly why test-tampering sensitivity is a reasonable proxy for lookup-detection sensitivity. Right now it does neither.

- The three-axes framing also conveniently avoids ranking. If forced to rank, NIST is unambiguously the closest peer on *both* threat model and audit architecture, which weakens the "underexplored area, only three thin peers" narrative the section needs.

**Recommendation**: replace §5.3's tidy framing with an honest "NIST is the closest direct precedent; Anthropic and ImpossibleBench are adjacent on different problems," and either drop the 42-50% number or explicitly say "this is sensitivity to a different kind of cheat; we cite it because no published number for lookup detection exists."

I checked ImpossibleBench's arXiv abstract page and could not confirm the 76% / 86-89% / 42-50% / 57-65% numbers from public-facing surfaces (the PDF was not text-extractable through WebFetch). The review presents these as load-bearing data points; if they trace only to figures or appendix tables, this should be flagged. **A reader should not assume numbers stated to two-decimal precision actually exist in a form the reader can find without downloading the PDF.**

### 1.2 The "external grounding" defense against Pan et al. 2024 is overclaimed for the scenario-quality supervisor.

§4 argues the QA scenario quality supervisor (`pr-98f670e`) is safe from Pan et al.'s shared-context reward-hacking finding because the supervisor reads "captured transcript via `--resume` (context separation)."

I verified Pan et al.'s abstract: the paper identifies "context sharing between the generator and the evaluator" as a factor influencing reward-hacking severity, alongside model size. The arXiv abstract page does not explicitly endorse "context separation" as *the* recommended mitigation — that framing is the review's, not Pan et al.'s. The published abstract describes the finding, not a prescription. The review smuggles a stronger claim ("the recommended mitigation is *context separation*") than the abstract supports.

More substantively: `--resume` reattaches to a prior session's state. Depending on how `pm` implements resume, the supervisor session may share *substantial* context with the scenario session — system prompt, transcript, scratchpad, tool-use history. That is the opposite of context separation in the Pan et al. sense (which would be a different model, or at minimum a fresh session with only the captured artifacts as input). Without a precise statement of what `--resume` carries forward and what it does not, the "context separation" claim is unverifiable. The review needs one of:

1. A specification of what state the supervisor session sees vs. doesn't see, with the claim that the not-seen state contains the parts Pan et al. flag, or
2. An honest "the supervisor shares model and partial context with the scenario; Pan et al.'s risk applies and the cap-at-2 amendment limit is the primary mitigation, not separation."

The current text picks the strong-claim side without earning it.

### 1.3 The §6 merge papers over the original split's weakness.

The introduction notes §6 "merges what an earlier draft split into two thinner sections." The merge does not, in fact, fix the underlying problem: the watcher-architecture material (§6.1) and the fakes-infrastructure material (§6.3) are *still* thin literatures, and merging them under "Operational Infrastructure" doesn't create density — it just renames the gap.

Specifically:
- §6.1's strongest peers (Dependabot, Renovate) are industry products with no architecture paper. AgentSpec and AgentAuditor are gestured at but not engaged: what do their rule languages actually do that the watcher gate does not? Neither paper's mechanism is summarized at a level the reader could use to judge similarity.
- §6.3 admits the test-double-for-LLM literature is thin and lists negative search results ("LLM mock," "record-replay LLM testing"). That is honest, but it also means §6.3 is a footnote dressed as a subsection. Cut it to one paragraph in §6.1 or be explicit that it's a "negative result" section.
- §6.2 (APR) is the genuinely strong subsection. It belongs structurally next to §3 (test generation), not buried at the end of §6, because the bug-fix flow is conceptually a test-then-repair pipeline that mirrors the test-generation pipeline.

**Recommendation**: move §6.2 forward (near §3), demote §6.3 to a paragraph, and rename §6 honestly to "Watcher Architectures (industry-dominated)."

### 1.4 The "compounding regression library" claim is still asserted without a measurable target.

The Conclusion says "regression tests *compound*" and calls this "the load-bearing payoff that grounds the next iteration rather than relying on intrinsic reasoning improvement." This claim appeared in §3 too. Neither place defines what "compounding" means quantitatively. Compounding *what*? Number of scenarios? Coverage? Bug-catch rate over time?

The closest analog the review cites is OSS-Fuzz's growing corpus, and OSS-Fuzz has actual numbers (bugs found per week, corpus size growth). The review borrows the rhetorical move without borrowing the measurement discipline. If the plan's payoff is "compounding," the review should either:
- Define the metric (e.g., "scenario count over time, coverage delta per scenario, bug recurrence rate"),
- Anchor against OSS-Fuzz's published numbers,
- Or drop the word "compounding" and use the weaker but honest "durable."

Right now "compounding" is doing aspirational rhetorical work the design hasn't earned with a target.

### 1.5 The §1 benchmark table is decoration, not signal.

The table has six columns (year, granularity, network access, contamination defense, evaluator) over nine rows. After reading the prose, a reader gains essentially nothing from the table that wasn't in the paragraph immediately preceding it. The "Evaluator" column reads "hidden tests" or "hidden unit tests" for eight of nine rows — that column carries no information. "Network access" is "sandboxed" for seven of nine. The table looks like signal but is mostly the same datum repeated.

**Recommendation**: either cut the table, or replace it with a 2D plot of the actually-differentiating axes (contamination-defense strength × task realism), with a marker showing where the plan's capstone sits.

### 1.6 The ASCII diagrams: one works, one doesn't.

- The Self-Refine → Reflexion → ChatUniTest → scenario-supervisor lineage diagram in §4 (lines 80-94) is decoration. It restates the prose immediately above it with arrows. A reader who follows the prose gets nothing extra from the ASCII; a reader who skipped the prose can't parse the ASCII because the labels are too compressed. Cut it.
- The 2x2 quadrant diagram in §6.1 (lines 159-171) is the only diagram that does work — it places the plan in a sparsely-populated region and the placement is the point. Keep it but label the axes "live internet access" vs "snapshot benchmark" instead of "online vs offline" (which is overloaded — see Block 3).

### 1.7 The citation-graph walk paragraph (Conclusion, line 197) is perfunctory.

The Conclusion lists thirteen works the walk surfaced. Of those:
- Huang, Pan, Anthropic alignment auditing, ImpossibleBench, METR, Agentless, AutoCodeRover, SapFix, GenProg, EvalPlus, TestPilot, AgentSpec, AgentAuditor, SWE-Bench Multimodal — these are all from 2023-2026 and trivially reachable from a single citation search on any of the seeds. They are not "graph walk" results; they are "first page of arxiv-sanity / Google Scholar with the seed name typed in" results.
- A genuine citation-graph walk would surface less-obvious work: e.g., FBInfer / Pysa-style static analyzers as automated-finding sources adjacent to bug-fix watchers; the "self-debugging" literature (Chen et al. 2023 "Teaching Large Language Models to Self-Debug") that bridges Self-Refine and code-execution feedback and which the review never cites; **SWT-Bench** (Mündler et al. 2024) which evaluates LLMs at generating tests rather than fixing bugs and is the direct missing peer for §3's QA scenario planner; **TDD-Bench Verified** and similar test-first benchmarks; the "judge model" literature for LLM-as-evaluator (Zheng et al. 2023 MT-Bench, Chen et al. 2024 on judge sensitivity) which is squarely relevant to §5's audit design.

The review acknowledges the walk was budgeted but doesn't acknowledge the budget was too tight to clear the threshold the methodology asks for ("directly-relevant prior work the reviewer didn't surface").

**Specific missing citations**:
- Chen, Lin, Yen et al. 2023, "Teaching Large Language Models to Self-Debug" (arXiv:2304.05128). Bridges §4 (self-refinement) and §3 (test feedback) cleanly.
- Mündler et al. 2024, "SWT-Bench: Testing and Validating Real-World Bug-Fixes with Code Agents" (arXiv:2406.12952). Direct peer for §3's `pr-2680fbf` scenario authoring.
- Zheng et al. 2023, "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena" (NeurIPS 2023). Foundational for any LLM-as-evaluator pipeline (the audit, the scenario-quality supervisor).
- R2E / R2E-Eval (Jain et al. 2024) — repository-level test generation with executable feedback.
- "Self-Edit" (Zhang et al. 2023, ACL 2023) — code generation with execution-result feedback.

### 1.8 Methodological flaw: ProgramBench is cited as a peer-reviewed benchmark with a leaderboard, but the only references are a website and "arXiv:2605.03546."

That arXiv ID is in the year 2026 future. The website snapshot date is the same week as this review. The review treats ProgramBench's design as established context (the capstone's "spirit" is borrowed from it; §1's contamination-defense story leans on it; the §6 quadrant places "ProgramBench" in the offline corner). If ProgramBench is a project the same team produced — or a benchmark with a leaderboard fewer than ten people have ever used — the review owes the reader that disclosure. As written, ProgramBench reads as an established benchmark on par with SWE-Bench. The asymmetry of evidence (peer review for SWE-Bench, a website-snapshot for ProgramBench) should be in the text, not hidden in the reference list.

### 1.9 The METR citation is doing more work than its source can support.

METR's reward-hacking blog post is cited as "the most current empirical data point on this threat surface" and three concrete incidents are described (Python call stack tracing, CUDA-sync disabling, disavowal under questioning). The review treats these as load-bearing for §5.2. But:
- METR's report is a blog post in a research-org's outreach channel, not a peer-reviewed paper.
- The cited behaviors are from RE-Bench, which is an ML-research-engineering benchmark, not a coding benchmark. Whether RE-Bench's cheating modes generalize to the capstone's code-and-internet setting is exactly the kind of leap the review elsewhere criticizes.

The review should either bracket METR as "suggestive industry signal, not generalization-tested" or cite peer-reviewed reward-hacking studies (Skalse et al. 2022, "Defining and Characterizing Reward Hacking," NeurIPS 2022; Pan et al. 2022, "The Effects of Reward Misspecification") that have the methodological backing.

### 1.10 The "ten seed references" passage in the Conclusion is muddled.

Lines 195-197 enumerate ten references but then in the same paragraph claim they cover "benchmark genealogy (1, 2), agent architecture (3, 4 via Wang et al.; SWE-Bench's companion SWE-agent), self-improvement and its bounds (3 and Huang via 5), contamination and runtime cheating (5, 6, 7, 8), and the test-generation primitive (10)." The numbering in the parenthetical does not match the numbered list in the prose. This is genuinely confusing and reads like a partial edit. Either drop the numbered indices or fix them.

---

## Block 2 — Structure and Readability

### 2.1 The Introduction is dense and front-loads jargon before motivating the work.

Lines 5-9: in three sentences the reader sees "regression-test suite," "Claude as both the thing that runs the tests and the thing that watches," three "watcher" processes by role, "pull requests," "scenario-quality supervisor," "capstone PR," "single-prompt task evaluation," "post-run integrity audit," "ProgramBench," "offline benchmarks," "leaderboard purposes." A reader who closed the tab here would not know what `pm` does or why they should care. The Introduction needs a one-sentence opener that says, in plain English, what problem the plan is solving and who benefits. Suggested replacement opener:

> "This review surveys the published work behind a plan to make a regression-test suite — the part of a software project that catches old bugs from coming back — into something that also *notices* what it isn't yet catching, and files work for itself when it does."

Then introduce the watcher / supervisor / capstone vocabulary one term at a time across the next two paragraphs.

### 2.2 §1 opens with "shifted three times in five years" but doesn't say why the reader should care which shift they're currently in.

Replace the opener with: "If you want to know whether a coding assistant is any good, you need a test it hasn't already seen the answer to. The history of those tests has three eras, and the plan's capstone evaluation sits in the third."

### 2.3 §5 has the highest information density and the worst signposting.

§5.2 introduces a "threat surface" bullet list (lines 117-122) without telling the reader what they will do with it. The list reads like a checklist for the audit's design, but the next subsection (§5.3) talks about peers, not about how the audit responds to each item in the list. Either:
- Use the list as the spine for §5.3 (peer 1 covers items A and C, peer 2 covers item B, etc.), or
- Cut the list and put its items as inline phrases in the §5.3 discussion.

### 2.4 The two "Bridge to §N" mini-sections (lines 100-102 and 141-143) are good in principle and weak in execution.

Both bridges restate what just happened and what's coming next, but they read like a lecturer's segue ("So if Section 4 was about X, Section 5 is about Y") rather than telling the reader *why the next section follows from the previous one*. The §5→§6 bridge is the worst offender: "the shift is from 'is one run sound?' to 'how do you run many runs continuously'" — that is two unrelated shifts (single→many *and* run→loop) stapled together. The actual logical bridge is that §5's audit is one operation; §6 is the infrastructure that runs that operation on a cadence.

### 2.5 Repetition: the Huang/Pan defense argument appears three times.

It's stated in §4 (lines 73-77), restated in the §4 ASCII timeline (lines 81-94), and summarized again in the Conclusion (line 191). The reader hears the same point three times. Pick one place to make it (§4) and have the others reference it.

### 2.6 The "ten seed references" passage (line 195) and the "citation-graph walk" passage (line 197) are adjacent and overlap.

Both lists enumerate works covering the same five threads. Merge them: "Seed papers and the walk that extended them."

### 2.7 The references section silently degrades from peer-reviewed citations to footnote-grade ones.

The references list mixes ICLR/NeurIPS papers with blog posts and snapshot URLs without flagging the difference. A reader skimming the list can't tell that "OpenHands SDK Team 2025, arXiv:2511.03690" is a preprint while "Jimenez et al. 2024 SWE-Bench ICLR" is a peer-reviewed publication. Split the references into "Peer-reviewed," "Preprints and arXiv-only," and "Industry / non-peer-reviewed" sections. The "Industry references" subsection at the bottom is half of this; finish the job.

---

## Block 3 — Non-Expert Accessibility (load-bearing)

The target audience is a PM / adjacent researcher / domain expert / hobbyist evaluating whether to use `pm`. Ordinary technical literacy, no software-engineering background. The review currently fails this audience badly. Below are the worst offenders with proposed rewrites.

### 3.1 Undefined jargon (software engineering)

The review uses load-bearing engineering vocabulary without any inline gloss. A non-developer reader will hit each of these and stop. Listed with proposed inline glosses on first use:

- **"regression-test suite"** (line 5, line 13 in intro paragraph): used before defined. Gloss: "regression-test suite (the collection of automated checks a project runs to make sure that fixing one bug or adding one feature does not re-break something that used to work)."
- **"pull requests" / "PRs"** (line 5, throughout): never spelled out, never glossed. Gloss on first use: "pull request — the standard mechanism in collaborative coding for proposing a change: one person writes a 'this is what I changed and why,' and another reviews it before it goes into the shared codebase."
- **"merge" / "merge bar"** (line 5, 98): undefined. Gloss: "merge — accept the proposed change into the shared codebase."
- **"unit tests" / "hidden unit tests"** (table, line 17): undefined. Gloss: "unit tests — small automated checks that run a single function and verify the output is what was expected."
- **"patch"** (line 19, "produce a patch that resolves the issue"): undefined. Gloss: "patch — the diff between the broken code and the fixed code; the proposed edit."
- **"diff"** (line 177): undefined. Gloss in context: "diff — the line-by-line difference between two versions of the same code."
- **"sandbox" / "sandboxed"** (table, line 21, §5.2): undefined. Gloss: "sandboxed — running inside an isolated environment so the code can't reach out to the rest of the computer or the internet unless explicitly allowed."
- **"transcript" / "tool-use transcript"** (§4, §5): the reader can guess "transcript" but "tool-use transcript" is opaque. Gloss: "the full log of every command the agent ran, every file it read, every web page it fetched, in order."
- **"allowlist"** (§5.2): undefined. Gloss: "allowlist — a written list of which external sources the agent is permitted to consult."
- **"CI" / "continuous integration"** (§6 heading "Automated program repair in CI"): undefined. Gloss: "CI (continuous integration) — the system that automatically runs the project's tests every time someone proposes a change."
- **"fuzzer" / "fuzzing"** (§3, §6): undefined. Gloss on first use: "fuzzing — automatically generating large numbers of weird or random inputs to a program to see what breaks."
- **"coverage" / "coverage gates" / "coverage plateau"** (§3, §4): undefined. Gloss: "coverage — the percentage of the program's lines or branches that the test suite actually exercises; high coverage means few corners of the code are untested."
- **"AST" / "abstract syntax tree"** (§2, §5.1): defined parenthetically in §5.1 but used unexplained in §2. Gloss on first use in §2: "AST (abstract syntax tree) — the structured tree-shaped representation a compiler builds from source code; lets the program be analyzed as a structure rather than as text."
- **"scaffold"** (§2, "mini-swe-agent is the deliberately-minimal scaffold"): undefined. Gloss: "scaffold — the surrounding code that gives a model its commands, file access, and step-by-step structure; the LLM itself is the engine, the scaffold is the chassis."
- **"sandbox," "egress,"** (§5.2): "real network egress" — undefined. Gloss: "egress — outbound connections from the sandbox to the internet."
- **"VCS"** (§6.3 heading): undefined. Spell out as "version-control system (the software that tracks changes to a codebase over time; Git is the dominant one)."
- **"mock," "test double," "fake"** (§6.3): these are distinct technical terms with overlapping meanings, all undefined. For a non-developer, gloss once: "test double — a stand-in for a real component used during testing, so the test can run without the real thing being available. A 'mock' is a strict stand-in that fails the test if called the wrong way; a 'fake' is a lightweight working substitute."

### 3.2 Undefined jargon (tool names)

- **"Claude" / "Claude Code" / "Claude Opus"** (throughout): the review uses these interchangeably and never tells the reader Claude is Anthropic's LLM, that Claude Code is the developer CLI built on it, and that "Claude Opus 4.7" is a specific model version. Add one sentence in the Introduction: "Claude is the language model from Anthropic that the plan uses as its engine; Claude Code is the command-line tool built on Claude that `pm`'s watchers invoke under the hood. Specific model versions like Claude Opus 4 are mentioned by name where the source paper uses them."
- **"GitHub" / "GitHub repository"** (throughout): assumed known. Gloss: "GitHub — the dominant online host for shared code projects; a 'GitHub repository' is one such project."
- **"npm"** (§3, "GitHub Next group's npm-focused test-generation tool"): undefined. Gloss: "npm — the standard package system for JavaScript code."
- **"Python," "JavaScript"** (passim): probably fine for the target reader, but the assumption is worth noting.
- **"Inspect"** (§5.3 line 131): glossed inline ("AISI/Anthropic's open-source evaluation framework"), which is good — but "AISI" is an undefined acronym in that very gloss. AISI = UK AI Safety Institute. Either spell it out or drop "AISI/" and say "Anthropic's open-source framework, originally built with the UK AI Safety Institute."
- **"CUDA"** (§5.2, METR description): undefined. Gloss: "CUDA — the software stack for running computation on Nvidia graphics cards; CUDA-sync is a timing primitive the agent disabled to fake faster wall-clock times."
- **"Codex CLI," "Aider," "Cline"** (§2): listed as practitioner tools without any indication of what they do. Gloss: "Aider, Cline, Codex CLI — command-line tools that let a human chat with an LLM to edit a project; the practitioner-facing analogs to Claude Code."
- **"Pynguin"** (§3): undefined. Gloss: "Pynguin — the leading classical (non-LLM) automated test-generation tool for Python."
- **"OSS-Fuzz / ClusterFuzz"** (§3, §6.1): partially glossed in §3, used unglossed in §6.1.

### 3.3 Undefined jargon (research vocabulary)

- **"ACI" / "agent-computer interface"** (§1 line 19, §2): defined parenthetically on first use ("ACI for short, used throughout the rest of this review"), but the definition is only "the set of editing and navigation primitives the model uses." For the target reader: "ACI — the menu of commands the agent has available: file-open, file-edit, run-tests, search-codebase. The argument is that what commands you expose to the model matters as much as which model you use."
- **"reward hacking"** (§4, §5, §5.2): used three times, never glossed. Gloss on first use: "reward hacking — when a model figures out how to score well on a measurement without actually doing the underlying task; for example, modifying the test instead of fixing the bug."
- **"intrinsic self-correction"** (§4 line 73): glossed in the same sentence as "without new information." Acceptable but tight. Strengthen: "intrinsic self-correction — asking the model to look at its own last answer and improve it, with no new data, no test result, no human feedback. Just 'try again, better.'"
- **"verbal RL" / "verbal reinforcement learning"** (§4): undefined. Gloss: "verbal RL — instead of updating the model's weights, the system updates a written 'lessons learned' note that gets pasted into the next attempt's prompt."
- **"actor-critic loop" / "actor-critic pattern"** (§4 line 98): this is the worst offender in the review. Two paragraphs of self-critique architecture come before the term, and then the review drops "actor-critic" with a parenthetical that uses *more* RL jargon ("reinforcement-learning vocabulary where an 'actor' proposes actions and a 'critic' scores them, then the actor updates against the critic's signal"). The target reader doesn't know what RL is, what an actor or critic is, or what "updates against the signal" means. Replace with: "the pattern of pairing a *writer* (which produces a candidate answer) with a *checker* (which decides whether to accept it, and if not, what to change). Rejected candidates get rewritten. The implementation watcher is the writer, the QA review loop is the checker."
- **"episodic memory" / "episodic-memory pattern"** (§4, §6.1): undefined. Gloss: "episodic memory — a written log of past attempts and what was learned from each; the next attempt reads the log before starting."
- **"alignment auditing"** (§5.3): undefined. Gloss: "alignment auditing — checking whether an AI model behaves the way its designers intended, especially under conditions where it might be tempted to misbehave."
- **"red-teaming"** (§5.3, "Breadth-First Red-Teaming Agent"): undefined. Gloss: "red-teaming — deliberately attacking a system to find weaknesses before a real adversary does."
- **"pass@k"** (§1 line 17): completely undefined. Gloss: "pass@k — a scoring metric: give the model k attempts at the problem, count it as 'passed' if any of the k attempts works. pass@1 means one shot; pass@10 means ten attempts."

### 3.4 Acronyms not spelled out on first use

- **"PR" / "PRs"** — pull request. Used from line 5 onward, never expanded.
- **"QA"** — quality assurance / testing. Used throughout; the only place it's defined is implicit.
- **"UX"** — user experience. Line 5, undefined.
- **"GVR"** — Generation-Validation-Repair. Defined in §3, good.
- **"ACI"** — already discussed.
- **"AST"** — discussed.
- **"APR"** — automated program repair. §6.2, defined inline. Good.
- **"DSL"** — domain-specific language. §6.1, undefined. Gloss: "DSL — a small specialized language designed to express one kind of thing very precisely; for AgentSpec, the language is 'rules an agent must obey at runtime.'"
- **"AISI"** — discussed in 3.2.
- **"VCR.py"** (§6.3): undefined. "VCR" here means "Video Cassette Recorder," used as a metaphor for record-and-playback of network calls. Gloss: "VCR.py — a Python library that records every network call a test makes the first time, then replays the recording on subsequent runs so the test doesn't actually hit the network."
- **"RL"** — reinforcement learning. §4, used in passing, undefined.
- **"LLM"** — large language model. The review uses LLM in §3 onward without ever spelling out. The reader of this review needs the term defined once at first use.

### 3.5 Names dropped without one-line context

Every named work needs *what it is, what it does, why it's cited here.* Currently many appear with only one or two of the three:

- **"Codex"** (§1, §3): the model behind GitHub Copilot. Not explained. The HumanEval paper is "the Codex technical report" — the reader doesn't know what Codex is.
- **"Cognition Labs"** (§2): named without saying it's a startup; "Devin" is named without saying it was the first agentic coding product to get viral attention.
- **"Anthropic"** (§5.3): assumed known. Gloss on first use: "Anthropic — the company that makes the Claude language model the plan uses."
- **"METR"** (§5.2): glossed nowhere. METR is Model Evaluation and Threat Research, an AI-safety eval org. Gloss: "METR — an AI-safety evaluation nonprofit that publishes findings from running frontier models through challenge tasks."
- **"AISI"** — discussed.
- **"NIST"** / **"CAISI"** (§5.3): NIST is glossed nowhere. CAISI is glossed nowhere. Gloss: "NIST — the US standards agency; CAISI is its AI Safety Institute, which has begun publishing methodology for evaluating whether AI agents cheat on tests."
- **"Liars' Bench"** (§5.3, line 137): name-dropped with no description. Cut or describe.
- **"GitHub Next"** (§3, in TestPilot description): undefined.
- **"Schäfer, Nadi, Eghbali, Tip"** etc: author lists without first-name initials or affiliations look like name-dropping. Either lead with the project name and bracket the citation ("TestPilot [Schäfer et al. 2023]") or accept that the prose-with-citations style is unfriendly to the target reader.

### 3.6 Quantitative claims without scale anchors

- **"42-50% sensitivity"** (§5.3 line 135): the reader doesn't know what sensitivity is, what it's sensitivity *to*, or whether 42% is "alarmingly low" or "surprisingly high." Anchor: "the monitor catches the cheat 42 to 50 percent of the time. That's roughly a coin flip — a bar low enough that any audit relying on a similar LLM monitor should expect to miss half the complex cases."
- **"86-89% sensitivity"** (same): "catches the cheat almost nine times out of ten in the simpler cases."
- **"76% on Impossible-SWE-Bench for GPT-5"** (§5.3): "in three out of every four runs, GPT-5 modifies the test rather than fixing the bug." Without that anchor, 76% reads neutrally; with the anchor, it's alarming, which is the review's point.
- **"19-29%"** EvalPlus drop (§1): "scores fell by roughly a fifth to nearly a third when the tests were tightened — meaning a substantial fraction of code that 'passed' the original benchmark was actually wrong."
- **"32.0% at $0.70 per task"** (§2, Agentless): the dollar number is anchored (cheap), the 32% is not. "Roughly one out of every three real GitHub issues was successfully fixed by Agentless's three-step pipeline."
- **"72% resolve rate"** (§2, OpenHands SDK): "roughly seven out of ten SWE-Bench Verified tasks resolved."
- **"10-13% / 42%"** Anthropic investigator (§5.3): "the investigator identifies the right root cause about one time in eight by itself; aggregating multiple parallel investigators raises that to roughly two in five."
- **"19% success rate at $0.43"** (verified above, but not in current review): if AutoCodeRover's numbers appear in a later revision, anchor them too.

### 3.7 Unmotivated framings

- **"That last choice is the plan's biggest research bet"** (Conclusion, line 193): the phrase "biggest research bet" assumes the reader is invested in the plan's outcomes as a research project. The target reader may just want to know whether to use `pm`. Replace with: "If the plan succeeds, this is the most distinctive thing it will have shown; if it fails, this is the most likely point of failure."
- **"deliberate departure from offline benchmarks"** (Introduction, line 5): assumes the reader thinks offline benchmarks are a default worth departing from. Motivate: "Most existing tests put the model in a sealed room without internet, on the theory that this is the only way to be sure it isn't cheating. The plan bets that a sealed room measures the wrong thing, because real engineers use the internet constantly."
- **"the case for it is..."** (§6.1 line 155): the section gives the case-for and case-against for dynamic priority re-derivation. Good in form, but the case-for assumes the reader cares about staleness in priority fields. Motivate by example: "Imagine the project just suffered a production outage. A stored priority list written yesterday wouldn't know. A priority that re-derives each tick reads the latest notes and reshuffles."

### 3.8 Dense paragraphs

- §1 paragraph at lines 17-21 (six sentences, four distinct ideas): split after "...interpret." Move the EvalPlus discussion to its own paragraph.
- §4 paragraph at lines 73-77 (eight sentences, three threads — Huang's claim, the bound, Pan's claim, the plan's response): split into three paragraphs, one per thread.
- §6.1 paragraph at lines 153-155 (the dynamic-prioritization argument): six sentences, three sub-arguments. Split.
- §5.3 paragraph at lines 137-139 (line 137 is itself a six-line paragraph with two ideas — deception-detection peers + assessment of the audit space): split.

### 3.9 "Why should I care?" check on section openings

Every section currently opens with a technical statement, not a benefit. Revised openers:

- **§1**: "If you want to know whether a coding assistant is any good, you need a test it hasn't already seen the answer to." (already proposed)
- **§2**: "The agents that write code under the hood of tools like Aider and Claude Code all derive from a handful of designs. Knowing which ones the plan borrows from tells you where to look for the plan's weaknesses."
- **§3**: "When the plan's regression tests miss something, the tool tries to write a new test on the fly. There's a decade of research on whether that ever works."
- **§4**: "When you ask a language model to grade its own work, sometimes it gets better and sometimes it gets worse. The research literature has figured out when each happens, and the plan is designed to land on the 'gets better' side."
- **§5**: "If the plan's evaluation lets the model use the internet, the model could just look up the answer. This section is about whether anyone has figured out how to tell when it does."
- **§6**: "The plan runs three background processes that share the work of catching and fixing bugs. This section places that design next to its industry and academic precedents."

### 3.10 Insider-only quips

- **"The honest assessment"** (§5.3 line 139): signals authorial self-awareness without adding substance. The reader is owed honest assessment everywhere, not a sign saying "this part is honest."
- **"The walk was deliberately budgeted"** (Conclusion line 197): hedging that admits a limitation without saying what would have been found with a fuller walk. Either name what would have been found (and then add it) or drop the hedge.
- **"As written, ProgramBench reads as an established benchmark"** — this is in my own Block 1 finding, but the review's text has similar moves: "as discussed" (§2), "as we'll see" (§4). These are lecturer's connectives that don't earn their keep. Cut.

### Tested rewrites

Per methodology, three of the longest accessibility findings reread for fresh jargon:

1. **"regression-test suite"** gloss: "regression-test suite (the collection of automated checks a project runs to make sure that fixing one bug or adding one feature does not re-break something that used to work)." Reread: introduces "automated checks" — should be fine for target reader. "Codebase" might appear later and need its own gloss. **Passes.**

2. **"actor-critic loop"** rewrite: "the pattern of pairing a *writer* (which produces a candidate answer) with a *checker* (which decides whether to accept it, and if not, what to change). Rejected candidates get rewritten. The implementation watcher is the writer, the QA review loop is the checker." Reread: uses "implementation watcher" and "QA review loop" — both need their own glosses earlier in the document. Assuming those are in place: **passes.** If they aren't yet glossed: still introduces jargon. Add: "(the implementation watcher is the background process that does the writing; the QA review loop is the part that grades the writing.)"

3. **"reward hacking"** gloss: "reward hacking — when a model figures out how to score well on a measurement without actually doing the underlying task; for example, modifying the test instead of fixing the bug." Reread: "model," "score," "measurement" all in the reader's working vocabulary. **Passes.**

---

## Appendix: What Cycle 1 Missed (cross-reference, written after independent review)

After completing the above, I read `REVIEW_CYCLE_1_LITREVIEW.md` and `REVIEW_RESPONSE_CYCLE_1_LITREVIEW.md`. Items my review caught that Cycle 1 did not:

1. **The three-axes framing in §5.3 is its own form of overstatement** (1.1). Cycle 1 pushed on the closest-published-peer question but accepted the three-axes resolution. My review notes the resolution is its own rhetorical maneuver — NIST does double duty on threat model *and* architecture, and ImpossibleBench's sensitivity numbers are for a different cheat type than the audit detects.

2. **The Pan et al. "context separation" mitigation is overclaimed** (1.2). Cycle 1 raised the reward-hacking-applicability question but apparently accepted the response's framing. My review verifies against the Pan et al. abstract: the paper identifies context-sharing as a factor, but the abstract does not explicitly endorse "context separation" as the mitigation. The review is putting words in Pan et al.'s mouth.

3. **The §6 merge is renaming, not consolidation** (1.3). Cycle 1 may have prompted the merge; the merge happened but the underlying density problem is unchanged. §6.3 in particular is still a footnote-as-subsection.

4. **The "compounding regression library" claim is still unmeasured** (1.4). The conclusion still asserts "compound" without a metric.

5. **The benchmark table is decoration** (1.5). Cycle 1 doesn't appear to have pressed on this.

6. **The ProgramBench asymmetry-of-evidence problem** (1.8). ProgramBench is treated as a peer to SWE-Bench despite being cited only as a website snapshot and a future-dated arXiv ID.

7. **METR is doing more work than its source supports** (1.9). Cycle 1 likely accepted METR as evidence.

8. **Missing citations**: Chen et al. 2023 self-debug, Mündler et al. SWT-Bench, Zheng et al. LLM-as-Judge, Self-Edit. The citation-graph walk was budgeted too tightly to clear the threshold the methodology asks for.

9. **The numbered references in the Conclusion don't match the prose** (1.10). Likely a partial edit Cycle 1 didn't catch.

10. **Block 3 — accessibility — at the level of specific proposed rewrites for every offender.** Cycle 1 may have raised accessibility issues; my review provides the per-term gloss text as the methodology requires.

Items Cycle 1 may have caught that mine did not press on equally hard: I did not deeply attack the citation-by-citation correctness of every reference (Cycle 1 reportedly found citation errors that were fixed); I treated the reference list as roughly trustworthy after spot-checking five (Huang, Pan, Agentless, AutoCodeRover, Anthropic alignment-auditing) and finding the characterizations approximately correct. A Cycle 3 should re-check the references I didn't spot-check, particularly the ones that exist in industry-blog form rather than peer-reviewed form (METR, Cognition's Devin post, the Anthropic alignment-auditing note, the Tembo 2026 guide).
