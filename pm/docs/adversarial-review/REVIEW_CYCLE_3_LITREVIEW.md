# Cycle 3 Adversarial Review — Literature Review

Reviewer: fresh Claude session, blind to prior cycles.
Artifact: `pm/docs/literature-review.md` (~8,477 words after two edit cycles).
Audience held in mind: non-developer evaluating `pm` (PMs, adjacent researchers, hobbyists with ordinary technical literacy).

This review is organized into three blocks per METHODOLOGY.md. Findings under each block are ordered roughly by load-bearing severity. After the three blocks, I give a convergence assessment, then a cross-reference appendix written after scanning the prior cycles.

---

## Block 1 — Substance

### B1-1. The ImpossibleBench "best-available proxy" framing in §5.3 is still doing rhetorical work the data don't license.

§5.3 now says ImpossibleBench is the "best-available proxy for 'how good can an LLM-as-monitor get on a complex agentic trace?'" That softer framing is honest about the cheat-type mismatch, but it conceals a second mismatch the reader is not told about. ImpossibleBench's cheating happens in a setting where the *task itself is impossible* — the spec contradicts the tests. The monitor's job there is to notice a structurally-detectable deviation: the model has provably altered a unit test, overloaded `__eq__`, or hard-coded test inputs. These are all *artifact-visible* cheats: the patch itself contains the evidence.

The capstone audit is supposed to detect a *trace-visible* cheat — the artifact looks fine, but the transcript shows the agent fetched the answer from a forbidden URL. The two settings differ on (a) what kind of cheat, (b) whether the artifact carries the cheat, (c) whether the task is solvable honestly at all. The 86-89 percent / 42-65 percent numbers in §5.3 are detection rates against (a)+(b)+(c) jointly. Calling them a proxy for the capstone audit's harder problem (where only the trace carries the signal, the task is solvable honestly, and the agent has a strong honest baseline) imports a generous prior the data don't support.

The honest move is either: (i) drop the numbers from §5.3 and say "no analogous numbers exist; the audit's sensitivity is an open question and a measurement obligation," or (ii) keep ImpossibleBench but state explicitly that the proxy direction is unknown — it could either be *easier* (trace lookups have URLs in them) or *harder* (the artifact looks identical) than ImpossibleBench's test modification, and the plan does not know which.

The current framing reads as a small honesty concession riding a large cite. I would tighten it further.

### B1-2. The `--resume` discussion in §4 succeeds at honesty but leaves the supervisor architecture in a worse evidentiary position than the prior version.

§4 now flags that `--resume` "carries forward the session's accumulated state — system prompt, prior turns, tool-use history. It does not run as the same continuous reasoning process. The exact degree to which this counts as 'context separation' in Pan et al.'s sense is unsettled." That is genuinely honest.

But: combined with "the amendment cap (default 2) is the primary mitigation; the `--resume` arrangement is a secondary reduction of shared context that has not been independently validated," the QA scenario quality supervisor (`pr-98f670e`) is now defended chiefly by *iteration capping*. Pan et al. 2024 is about how shared context corrupts iterative refinement; the plan's defense is to limit the number of iterations. That is a legitimate but weak defense — Pan et al. show reward hacking appears within very few iterations, sometimes by iteration 2. Two amendments is exactly the regime Pan et al. found measurable hacking in.

The plan needs either: (i) measurement showing the amendment cap is sufficient at n=2 (not present), (ii) an actually-separate session — fresh process, no `--resume`, only the captured artifacts as input — as the supervisor's default, or (iii) explicit acknowledgement that this is the load-bearing unvalidated piece. The current text picks (iii) lightly but does not pull the consequence through to the Conclusion's listing of "where the plan reuses prior work." A reader who follows the chain may end this review more skeptical of `pr-98f670e` than when they started.

### B1-3. ImpossibleBench numbers — independent verification turned up a discrepancy.

The review states "in three out of every four runs, GPT-5 modifies the test rather than fixing the bug, a 76 percent cheating rate on Impossible-SWE-Bench." Independent fetch of arXiv:2510.20270 (HTML rendering) reports GPT-5 cheating rates of 54.0 percent on Conflicting-SWEbench (full scaffold) and 2.9 percent on Oneoff-LiveCodeBench. I did not find a "76 percent" figure for GPT-5 on Impossible-SWE-Bench in the abstract or the section visible to me. This may be a different cut of the same data (e.g., a different prompt regime, a different definition of "cheat"), but the review does not cite the specific table or section and the prose presentation of "three out of four" reads as definitive. Either pin the number to a specific table-and-cut or soften the prose to "the majority of runs in at least some conditions."

### B1-4. AgentAuditor NeurIPS 2025 status is confirmed; OpenHands status needs an upgrade.

Independent verification:

- AgentAuditor (arXiv:2506.00641): confirmed NeurIPS 2025. The review's hedge ("Listed as NeurIPS 2025 by the abstract; treat as preprint until proceedings appear") was appropriate when written; it can now be promoted to "NeurIPS 2025."
- OpenHands (Wang et al., arXiv:2407.16741): **confirmed accepted at ICLR 2025 (Poster).** The review currently lists this as "OpenReview submission" in the Preprints section. This is now inaccurate — it should move to Peer-reviewed publications with venue "ICLR 2025."
- Liars' Bench (Schwettmann et al.): the OpenReview entry exists; the canonical title is "Liars' Bench: Evaluating Lie Detectors for Language Models" (arXiv:2511.16035, November 2025). The review uses "Evaluating Deception Detectors for AI Assistants," which appears to be an earlier OpenReview title variant. Update the title to match the published/preprint form and add the arXiv id.

### B1-5. §6's "no priority field stored anywhere" claim conflicts with the work-log it then cites as part of priority derivation.

§6 says: "There is no priority field stored anywhere. The watchers re-judge priority every tick from a combination of prompt-supplied generic guidance, work-log context (Reflexion's episodic-memory pattern applied across ticks), and user notes."

If the work-log carries forward signals that re-bias priority (and it does — that's the Reflexion analogy), then priority *is* persisted, just in unstructured prose form. The distinction the plan is making is "no structured priority field" vs "no persisted priority signal." The latter is what the prose claims; the former is what is actually true. This matters because the case-against ("re-deriving priority every tick costs LLM calls and risks oscillation") is exactly the concern that motivates a structured priority field, and a reader will notice the work-log smuggles state through the back door. Tighten to "no structured priority field; priority signals persist informally in the work-log and are re-weighted each tick."

### B1-6. The Conclusion's compounding-metrics passage is the only place numbers-to-be-collected are named, and they are named loosely.

"Compounding — measured here as net growth in regression-test count over time, coverage delta per scenario, and bug-recurrence rate — would mean the corpus does more work each cycle than it did the cycle before."

Three problems. (a) "Net growth in regression-test count" is gameable in the obvious way: a watcher can spam low-quality scenarios to inflate the count. The plan's scenario quality supervisor is supposed to defeat this, but the metric itself doesn't acknowledge the dependency. (b) "Coverage delta per scenario" is well-defined in coverage tooling but mute on diminishing returns — early scenarios cover the most surface, later ones add little. (c) "Bug-recurrence rate" requires a denominator (recurrences per known-fix-merged, recurrences per time window?) that the prose elides. For a section gesturing at the measurement obligation the rest of the review pins as the plan's intellectual debt, this is too loose. Either commit to specific operational definitions or admit the metrics are aspirational.

### B1-7. The "durable" vs "compounding" distinction is present and correct; the §3 / Conclusion treatment is slightly inconsistent.

§3 calls the generated tests "durable" and contrasts with throwaway suites. The Conclusion shifts to "compounding" with the metric gloss above. The §3 framing is what the plan can claim today (the test survives the run); the Conclusion framing is what the plan would *like* to claim once metrics are collected. The distinction is principled — but a reader who notices both will not see them clearly distinguished. Add one sentence at the §3 / "durable" passage saying: "Whether durable tests *compound* — produce more value per cycle than the cycle before — is a separate question taken up in the Conclusion."

### B1-8. The capstone's placement in the 2D plot's "cleanroom" row is wrong — or the axis is mis-labeled.

The plot at lines 50-68 places the capstone in the "cleanroom" row. The capstone's runtime posture is the opposite of cleanroom: it grants real internet access. The cleanroom characterization only applies *post-run* — the audit walks the trace after the fact. ProgramBench, in the same row, is cleanroom *at runtime* (no internet allowed). These two are not the same axis.

Either: (i) split the row into "cleanroom-at-runtime" (ProgramBench) and "audit-after-run" (the capstone), or (ii) re-label the axis as "what does the test do to prevent the agent from looking up the answer" — and acknowledge that the answers are categorically different (denial vs detection). The current plot makes the capstone look like a stricter version of ProgramBench, when actually it is a methodologically opposite bet. This is a real taxonomy ambiguity, not a phrasing nit; the §6 plot (live-internet vs no-internet on one axis, snapshot vs continuous on the other) does this taxonomy correctly. The §1 plot should be reconciled with §6's framing.

### B1-9. Missing peer not in the review: VeRA / verifier-guided agentic generation literature.

The review treats "an external verifier checks the model's work" as a single pattern. The recent literature has split that into a sub-genre: verifier-guided generation, where the verifier is a separately trained model or a separately tuned LLM whose only job is to grade. Cobbe et al. 2021 "Training Verifiers to Solve Math Word Problems" is the well-known reference. Lightman et al. 2023 "Let's Verify Step by Step" (NeurIPS 2023, OpenAI) is the process-reward modeling precedent. The plan's scenario quality supervisor is structurally a verifier on top of a generator; the review does not engage this lineage at all, only Pan et al. 2024's hacking critique of it. This is a citation gap: the plan is in a sub-genre with its own positive literature, not just a hacking critique.

### B1-10. The plan's bug-fix flow as "Self-Debug at the iteration level" understates the difference.

§3.2 / Conclusion say `pr-30588a7` is "structurally a Self-Debug loop with the failing test as the external feedback signal." Chen et al. 2023 Self-Debug operates at the *generation step* — model generates candidate, executes, refines within one prompt-response cycle. The plan's bug-fix watcher operates at the *watcher-tick level* — many minutes apart, with a work log between ticks. These are not the same iteration granularity, and the differences (longer feedback loop, persistent work log, intervening discovery-supervisor activity) change the failure modes (drift, stale context, conflicting concurrent work). Either acknowledge the granularity difference or pick a closer analog (perhaps SapFix's batched-deployment cadence).

---

## Block 2 — Structure and Readability

### B2-1. The 750-word glossary spine in the Introduction is a real obstacle for the stated audience.

A non-developer arriving at this document is asked to internalize 14 defined terms before they reach the first substantive section. Several of them depend on others (e.g., "QA review loop" uses "regression tests" defined two bullets later; "auto-sequence" assumes the reader has parsed "watcher" and "implementation"). The reader who came to evaluate `pm` did not commit to a vocabulary list before deciding whether the tool is interesting.

Concrete fix: move the glossary to an Appendix labeled "Terms used in this review" and replace it in the introduction with a 100-word "what the plan does" plain-English summary followed by a "Terms used throughout — defined in the appendix" inline anchor list (no definitions, just names). The first technical section's load-bearing terms get glossed *on first use* within the section, even if redundant with the appendix. The reader can either skim the appendix once or trust the inline glosses, but they are not forced to read 750 words of definitions before they get a hook.

### B2-2. §3 is now too large — it bundles test generation, APR, and fakes into one section, and the merge destroyed a useful organizing signal.

The section title is "LLM-Driven Test Generation, Fuzzing, and Automated Program Repair." That's three distinct subfields. §3.1 (test gen) and §3.2 (APR) are independently substantial; §3.3 (test doubles) is much shorter and on a third topic again. The previous structure (separate §3 and a separate APR section) gave the reader a natural pause at the transition. The merged version reads as a wall.

Concrete fix: either restore APR to its own section (§3.5 or a re-numbered §4, with the self-improvement section becoming §5), or add a one-line sub-TOC at the top of §3 listing its three subsections so the reader can navigate. The first option is structurally cleaner; the second is the minimum.

### B2-3. Section openings still don't tell the reader what they get from reading.

§3 opens with "When the plan's regression tests miss something, the tool tries to write a new test on the fly. There's a decade of research on whether that ever works..." — this passes the Block-3 check because it names a benefit.

But §5.1 opens with "The data-contamination question — has the model already seen the test? — has had a productive 2023-2024 literature." This does *not* tell the reader why they should read it. Propose: "Before you trust a benchmark score, ask whether the answer was already in the model's training data. This section is the literature on detecting that."

§6 opens with "The plan runs three background processes that share the work of catching and fixing bugs. This section places that design next to its industry and academic precedents." Passable but flat. Propose: "The plan's three watchers look a lot like Dependabot. Here's what is and isn't borrowed, and where the plan diverges."

### B2-4. The Conclusion's "Seed papers and the budgeted citation-graph walk" paragraph is inventory, not synthesis.

Lines 226 lists 25+ paper names in one paragraph. A reader who has just finished the document has already seen these names. Listing them again does not help anyone — it reads as accountability ("I considered all of these"), not exposition.

Concrete fix: cut the list. Replace with one sentence: "The full citation set, organized by section, is in the References. The walk remains under-budgeted for a full traversal; readers chasing a specific thread should treat the references as a starting set, not a complete one." If the budgeting note is the load-bearing part, it should appear as its own paragraph, not buried after a 25-name inventory.

### B2-5. The two short "Bridge to §5" and "Bridge to §6" passages are nearly content-free and should fold into the next section's opening.

Each is two sentences. They don't add information; they restate the upcoming section's premise. The body of §5 and §6 should open with the bridge content woven in. Cut the standalone bridges.

### B2-6. The §1 "task realism / contamination defense" 2D plot needs reconciliation with §6's plot — see B1-8.

Beyond the placement error, the §1 plot's column labels ("function completion / real issue on real repo / rebuild from binary") are clear, but the row labels ("none / human filter / time window / cleanroom") are mixed in kind: "human filter" is a method, "time window" is a constraint, "cleanroom" is an environment. The reader will not parse this taxonomy without effort. Either rebuild the row axis as a uniform-kind dimension ("strength of contamination defense, weakest to strongest") with brief inline characterizations, or split into two plots.

### B2-7. The discovery-supervisor / implementation-watcher / scenario-quality-supervisor hierarchy is described in prose three different times (Intro, §4, §6) without a single diagram.

A small ASCII diagram showing: external trigger → discovery supervisor → file PR → implementation watcher → QA review loop → scenario quality supervisor → merge gate, would be more valuable than any of the three prose descriptions. Currently the reader is asked to reconstruct it mentally from three slightly-different verbal descriptions.

### B2-8. The METR blog post receives a paragraph in §5.2; the framing-and-then-caveat is awkward.

The passage builds up to "CUDA-sync is a timing primitive the agent disabled to fake faster wall-clock times" and then immediately says "Treat the METR report as a suggestive industry signal rather than load-bearing data." If it isn't load-bearing, why is it the longest concrete-example passage in §5.2? Either commit to it as illustrative (and cut the caveat to one clause) or demote it to a footnote.

---

## Block 3 — Non-expert Accessibility (load-bearing)

For every finding I propose a specific replacement. Tested against the audience: PM / adjacent researcher / hobbyist with ordinary technical literacy.

### B3-1. Terms still used without inline gloss (after Cycle 2's gloss pass).

The following terms appear in the body of the review used load-bearingly and are not glossed at first body use. (The introduction's glossary spine doesn't count for Block 3 — a reader who skipped it or read it once and then forgot will be stuck.)

- **"pass@k"** (§1) — glossed inline; the gloss is OK but uses "attempts" and "model" without clarifying "k" is a hyperparameter you choose. Propose: "pass@k — a scoring metric: give the model `k` tries; count a pass if any try works. pass@1 means one try, pass@10 means ten." Make the count and the choice both explicit.
- **"diff"** (§1, line 42) — glossed only as "the proposed edit, expressed as a line-by-line diff." The reader doesn't know a diff is a comparison format showing additions and deletions. Propose: "patch (a diff — a line-by-line listing of what was added, removed, or changed in the file)."
- **"sandbox"** (§1 line 44) — glossed once on first use. Reused in §5.2 "a sandbox that grants real network egress." "Egress" itself is jargon. Replace: "a sandbox (isolated environment) that lets the agent reach out to the open internet."
- **"AST" / "abstract syntax tree"** (§2) — glossed at first use ("the structured tree-shaped representation a compiler builds from source code"), but "compiler" is itself jargon for this audience. Propose: "abstract syntax tree (AST) — a tree-shaped map of a program's structure, the way a sentence-diagram is a tree-shaped map of a sentence."
- **"flaky"** (§3.1) — "flaky assertions" appears with no gloss. Propose: "flaky assertions (checks that sometimes pass and sometimes fail for the same input)."
- **"mocked-out-too-much"** (§3.1) — assumes the reader knows what "mocking" is in a testing context. Propose: "tests that replace so many real components with stand-ins that they don't really exercise the code under test."
- **"evolutionary test generation"** / **"genetic programming"** (§3.1, §3.2) — neither is glossed. Propose for both: "(an older AI technique that breeds candidate solutions like genes, keeping the ones that perform best and mutating them to make the next generation)."
- **"DSL — domain-specific language"** (§6) — glossed, but the gloss "a small specialized language designed to express one kind of thing precisely" is OK; consider adding an example: "(e.g., SQL is a DSL for database queries; CSS is a DSL for styling web pages)."
- **"AST fingerprints"** (§5.1) — assumes the reader has retained the AST gloss across 1,500 words. Re-gloss inline: "AST fingerprints (compact summaries of a program's structural shape)."
- **"oracle access"** (§4) — appears once: "tool calls, ground truth, oracle access, where self-correction reliably helps." A non-developer does not know "oracle" in this sense. Propose: "oracle access (a trusted source the model can ask for the correct answer, like a graded answer key)."
- **"verdict surface"** (§5.2) — project-internal term, never defined. Propose: "verdict surface (the limited set of grades the system can emit — in `pm`, just `READY` or `INPUT_REQUIRED`)."
- **"actor-critic"** — does NOT actually appear (good), but **"writer-and-checker pair"** is introduced in §4 line 138 without being explicitly tied to the actor-critic literature even though the reader of the literature would expect it. Either name it or don't — currently it half-names it. Propose: "a *writer-and-checker* pair (called actor-critic in the research literature, but the plain names are clearer)."
- **"ICSE / OOPSLA / FSE / ISSTA / TSE / ACL / EMNLP / NeurIPS / ICLR / ICML / COLM / USENIX Security"** — venue abbreviations stack up. A non-developer does not know which of these are highly selective vs which are workshops. Propose: at the References section, prepend a one-line glossary: "Venue abbreviations: ICLR / NeurIPS / ICML are top general ML conferences; ICSE / FSE / ISSTA / OOPSLA / TSE are top software-engineering venues; ACL / EMNLP are top NLP venues; USENIX Security is a top security venue; COLM is the Conference on Language Modeling. All cited here are peer-reviewed unless marked otherwise."
- **"AST-based plagiarism detection"** (§5.1) — same compounding issue. Propose: "AST-based plagiarism detection — checking whether two programs have the same tree-shaped structure even if they were re-worded at the surface."
- **"pretraining contamination" vs "runtime contamination"** — the contrast is introduced clearly in the Introduction. But §5.1 / §5.2 names them again as "data-contamination" / "runtime-time" without referring back to the introduction's terms. Choose one vocabulary and use it throughout. The introduction's "pretraining contamination" / "runtime contamination" is the cleaner pair; §5 should use those.
- **"event-stream design"** / **"event-sourced"** (§2 OpenHands) — opaque to the target reader. Propose: "an event-stream design (every action between agent and environment is logged as a typed event in order, like a chat transcript that also captures the agent's tool calls)."
- **"AST fingerprints"**, **"prompt skeleton"**, **"scaffold"** — all introduced or reused once; only "scaffold" is glossed. Be consistent.

### B3-2. Glosses that introduced new jargon (the load-bearing failure mode).

- §1 line 38: "graded by hidden unit tests (unit tests are small automated checks that run a single function and verify its output)." "Verify its output" is fine. But "hidden unit tests" the reader meets *before* the gloss — the modifier "hidden" suggests the reader knows what unit tests are. Reorder: "graded by hidden tests — small automated checks (called unit tests) that run a function and confirm it produced the right output. 'Hidden' means the candidate doesn't see them, so they can't be gamed."
- §2 line 84: "AST-based program analysis grounds the LLM's code context, treating 'where in the AST does this bug live?' as a retrievable structured query rather than an emergent agent behavior." Three pieces of jargon in one sentence: "ground," "structured query," "emergent agent behavior." Propose: "AST-based program analysis: instead of letting the LLM browse the code freely, the system uses the program's structural tree to look up exactly where a bug lives, then hands that location to the LLM. (Like consulting a building's blueprint to find a leaky pipe, instead of wandering room to room.)"
- §4 line 124: "Reflexion's *verbal reinforcement learning* design — instead of updating the model's weights, the system updates a written 'lessons learned' note that gets pasted into the next attempt's prompt." Good. But "weights" is jargon (model parameters). Propose: "instead of retraining the model itself, the system updates a written 'lessons learned' note that gets pasted into the next attempt's prompt."
- §5.1 line 150: "edit-distance and AST-based plagiarism detection — comparing the abstract syntax trees of generated code against AST fingerprints of training-corpus code, on the rationale that AST structure survives the surface-level rewrites that defeat naive substring matching." "Edit-distance" is unexplained, "AST fingerprints" is unexplained, "naive substring matching" is unexplained. Propose: "two ways of detecting near-duplicates that survive renaming: edit-distance (how many character changes would convert one program into the other) and AST-based comparison (matching programs by their structural shape, not their literal text)."

### B3-3. Section openings that fail the "why should I care" check.

See B2-3 above; the proposed openings are restated:

- §5.1: "Before you trust a benchmark score, ask whether the answer was already in the model's training data. This section is the literature on detecting that."
- §6: "The plan's three watchers look a lot like Dependabot. Here's what is and isn't borrowed, and where the plan diverges."
- §3.2: "Once a failing test points at a bug, the next question is whether the tool can fix it on its own. That problem is called automated program repair (APR), and it has been worked on for over a decade."
- §3.3: "Testing code that calls an LLM is hard because every call costs money and gives slightly different answers. This section is about how the plan fakes the LLM during its own tests."

### B3-4. Numbers without scale anchors.

- "72 percent resolve rate on SWE-Bench Verified" — anchored ("roughly seven out of every ten"). Good.
- "32.0 percent at $0.70 per task" (Agentless) — partly anchored ("roughly one out of every three"). The $0.70 has no scale: is that cheap or expensive per task? Propose: "$0.70 per task — about the cost of a cup of coffee per bug fix; SWE-agent at the time was several dollars per task."
- "10 to 13 percent" / "42 percent" (Anthropic investigator) — anchored ("about one time in eight"; "two in five"). Good.
- "86 to 89 percent" / "42 to 50 percent" / "57 to 65 percent" — anchored as "almost nine times out of ten" / "roughly a coin flip on the harder cases." Good.
- "19 to 29 percent" drop under EvalPlus — anchored as "roughly a fifth to nearly a third." Good.
- **Unanchored**: "2,294 task instances" (SWE-Bench), "617 visual-software JavaScript tasks" (SWE-Bench MM), "500-task human-filtered subset" (SWE-Bench Verified), "200-task benchmark" (ProgramBench), "30+ package ecosystems" / "90+" (Dependabot / Renovate), "2K contributions from over 186 contributors" (OpenHands, in citation verification but not in the text — never mind). For the benchmark sizes, the reader doesn't know if 200 is small or large. Propose adding a one-line anchor: "these benchmarks range from a couple hundred to a couple thousand tasks; HumanEval at 164 tasks is the smallest of the modern set, SWE-Bench at ~2,300 is the largest."

### B3-5. Names dropped without context.

- **"GitHub Next group"** (§3.1) — glossed parenthetically ("GitHub's research arm"). Good.
- **"Cognition Labs"** (§2) — glossed. Good.
- **"Anthropic"** (§5.3) — re-glossed in passing. Good.
- **"Fowler's 'Mocks Aren't Stubs,'" "Meszaros's *xUnit Test Patterns*"** (§3.3) — these are software-engineering canon, completely opaque to the audience. Propose: cut both names; replace with "the classical testing-pattern literature that distinguishes mocks (strict stand-ins) from fakes (working substitutes)." If you need the citation, footnote it.
- **"Tembo's 2026 comparison, the Haseeb Qureshi gist"** (§2) — the audience does not know who Tembo or Haseeb Qureshi are, and "gist" is jargon for a GitHub-hosted code snippet. Propose: cut the names; say "informal practitioner comparisons exist; see the References for pointers."
- **"the bradAGI/awesome-cli-coding-agents directory"** (References) — opaque. Either gloss as "a community-maintained list" or cut.
- **"USENIX Security 2017"** for OSS-Fuzz — venue abbreviation never spelled out. Propose: USENIX Security is "a top academic security conference" (added once at the venue-glossary line proposed in B3-1).
- **"COLM 2024"** (AutoGen venue) — never spelled out. "Conference on Language Modeling." Add to venue glossary.
- **"Inspect"** (§5.3, NIST CAISI) — glossed as "Anthropic's open-source evaluation framework." Good. But the next sentence references "structured tool-use-transcript walks the capstone's audit needs to do" — "tool-use transcript" is glossed earlier but the reader will have to backtrack 700 words. Re-gloss inline.

### B3-6. Acronym creep.

Spelled out OK: LLM, PR, CI, QA, UX, ACI, AST, APR, DSL, NIST CAISI.

Not spelled out on first use:
- **TSE** (IEEE Transactions on Software Engineering) — appears multiple times in citations only; add to venue glossary.
- **OOPSLA, FSE, ISSTA, ICSE, ICSE-SEIP, EMNLP, ACL, ICML, ICLR, NeurIPS, USENIX, COLM** — venues. See B3-1.
- **GVR loop** (§3.1) — glossed inline ("Generation-Validation-Repair"). Good.
- **CUDA** (§5.2) — glossed inline. Good.
- **AST** — glossed; reused later without re-gloss. Acceptable, but see B3-1 on AST fingerprints.
- **MT-Bench** (Zheng 2023 reference) — appears in the References list but never in the body. If it's in the References but unused, cut it from References. If it's in the body somewhere I missed, gloss it ("a benchmark of multi-turn chatbot questions").

### B3-7. Insider-only quips or hedged language.

- "honestly negative result" (§3.3) — fine; reads as principled.
- "industry-tooling territory" (§3.3) — fine.
- "the closest peer in the literature" — used many times. Fine but starts to read as a tic. Vary phrasing: "the most similar academic work I could find," "the published analog," "the prior art that comes closest."
- "the load-bearing engineering bet" (§5.2) — "load-bearing" is engineering metaphor used densely throughout (I count 6+ occurrences). Some are warranted; others ("load-bearing detail," "load-bearing rebuttal") are filler. Audit and reduce by half.
- "the entry point that puts the plan in that quadrant" (§6) — vague. Propose: "the capstone is what makes the plan continuous-and-internet-enabled; without it the plan is just continuous-and-offline (which OSS-Fuzz already does)."

### B3-8. Section 5.2's bullet list is too dense.

```
- a sandbox that grants real network egress ...
- an agent with curiosity about how the reference solution looks
- a long enough horizon that one accidental fetch can poison the entire run
- transcripts that contain everything the agent did, but no flag for "this was the bad fetch"
- a downstream grader that scores the artifact, not the process, so a cheated solution and a legitimate one are indistinguishable at the verdict surface
```

For the target audience this is a wall. "Curiosity" anthropomorphizes; "poison" is jargon-y; "no flag for" assumes the reader knows transcripts have flags; "the verdict surface" is project jargon (see B3-1). Rewrite as plain prose:

"The audit has a hard problem because: the sandbox lets the agent reach the open internet (otherwise the test isn't realistic); the agent has reason to peek at how others solved the same problem; the run is long enough that one stray click can taint everything that follows; the trace shows every action but doesn't label any of them as cheating; and the grader only looks at the final answer, where a cheated and a legitimate solution look identical."

---

## Convergence Assessment

This review produced **roughly 25 substantive findings** across the three blocks. A meaningful subset (B1-1, B1-2, B1-5, B1-8, B2-1, B2-2, B2-4, B3-1, B3-2, B3-8) are clearly substantive: they ask the artifact to change a claim, restructure a section, or fix an accessibility failure that materially affects whether the target audience can read it.

A smaller subset (B1-7, B2-5, B2-8, B3-7) are starting to feel like phrasing nits — sentences I would rewrite but whose absence wouldn't materially mislead anyone.

Most importantly: the *kind* of finding has shifted across cycles in a way that is itself a signal. Cycle 1's substantive findings (per scan after independent review) were "missing citations" and "overstated claims." Cycle 2's were "still-overstated claims" and "non-expert reader hits a wall." Cycle 3's are "honest framings whose honesty exposes weak underlying defenses" (B1-1, B1-2) and "glosses introduced glosses with their own jargon" (B3-2). That is a converging pattern: the reviewer is now hunting in the corrections themselves, finding second-order issues.

**My recommendation: this is the natural last cycle.** B1-1 and B1-2 are genuinely the load-bearing remaining issues; if those two are addressed (either by tightening claims or by acknowledging the design owes future measurement), the artifact is in the regime where further cycles will produce phrasing nits. The Block 3 findings are still substantive — the glossary spine and the bullet list in §5.2 in particular — but they are *correctable in a single targeted edit*, not symptomatic of structural problems.

If a Cycle 4 happens anyway, the highest-value pressure points would be: (a) does the rewrite of B1-1 and B1-2 actually downshift the rhetorical work those passages do, or does it move the problem to a different sentence; (b) does the glossary-spine relocation (B2-1) preserve readability for the section-skipping audience; (c) is there a single architectural diagram of the watcher hierarchy that replaces three prose descriptions. I would not recommend Cycle 4 — the marginal value is low.

---

## What Cycles 1-2 Missed (cross-reference, written after independent review)

I have now scanned `REVIEW_CYCLE_1_LITREVIEW.md`, `REVIEW_CYCLE_2_LITREVIEW.md`, and the two response files. Items my independent review surfaced that they did not:

1. **The §1 plot's "cleanroom" row mischaracterizes the capstone's runtime posture vs its audit posture (B1-8).** Cycle 1 and 2 critiqued the plot's labeling and density but did not catch that ProgramBench and the capstone don't actually share an axis. This is a taxonomy error, not a presentation issue.

2. **The verifier-guided generation literature is a missing peer the plan sits inside (B1-9).** Cycles 1-2 demanded more citations on contamination, on multi-agent frameworks, on test generation, but did not flag Cobbe 2021 / Lightman 2023 as the positive-side literature corresponding to Pan 2024's negative-side critique. The supervisor architecture sits in a sub-genre the review does not name.

3. **The work-log smuggles state through the back door (B1-5).** Cycle 2 critiqued §6's "no priority field" claim from a different angle (asking whether re-derivation actually works); it did not catch that the work-log is itself a persisted priority signal in unstructured prose form.

4. **ImpossibleBench's 76% GPT-5 figure does not match the paper's tables I could reach (B1-3).** The prior cycles raised the cheat-type mismatch but did not independently verify the specific number cited.

5. **OpenHands is published at ICLR 2025 (B1-4).** The review still lists it as a preprint. Prior cycles flagged citation status as needing verification but did not catch this upgrade.

6. **The "durable" / "compounding" split is principled but presented inconsistently (B1-7).** Prior cycles did not separate these as distinct claims; my review names the seam.

7. **The METR passage's framing-then-caveat pattern (B2-8).** The previous cycles wanted more concrete examples in §5; they did not catch that the most concrete passage in §5.2 immediately defangs itself with a hedge.

8. **The glossary spine introduced nested terms — bullets that depend on later bullets (B2-1).** Cycle 2 applied the gloss spine in response to Cycle 1's "non-expert can't read this." It did not check that the spine itself is internally non-linear; the reader meets terms before their dependencies.

9. **Venue abbreviations are not glossed for a non-academic audience (B3-1, B3-6).** Prior cycles glossed research vocabulary but treated ICSE / OOPSLA / ICLR as transparent. They aren't.

10. **The bullet list in §5.2 is the densest accessibility wall in the document (B3-8).** Neither prior cycle flagged this specific list; both attended more to prose paragraphs than to list-form jargon clusters.

Conversely, what the prior cycles caught that I did not surface independently: the SWE-Bench Pro citation status, the Mündler / SWT-Bench addition, the AutoGen / MetaGPT separation in §4 (I implicitly accepted these as well-structured). They also surfaced specific page-by-page jargon counts I treated more holistically. The cycles converge: prior reviewers found citation gaps, I found taxonomy and proxy-validity gaps. Both are real; the artifact has improved across cycles, and at this point the remaining work is targeted edits, not structural rebuilds.
