# Block 4 Review — Literature Review (Autonomous Regression and Bug-Fix Loop)

Scope: prose craft only. Substance, structure, and accessibility were treated in prior cycles. Findings here are about how the document reads, not what it says.

---

## Paragraph-level findings

### P1. The opening sentence buries the lede in apposition

**Before (Introduction, ¶1):**
> This review surveys the published work behind a plan to make a regression-test suite — the collection of automated checks a project runs to make sure that fixing one bug or adding one feature does not re-break something that used to work — into something that also *notices* what it isn't yet catching, and files work for itself when it does.

The main verb (`surveys`) is fine, but the actual subject of the review — what the plan does — is split across two clauses with a 28-word parenthetical between them. By the time the reader reaches "files work for itself," the grammatical thread is gone. The italics on *notices* land flat because the antecedent is buried.

**After:**
> This review surveys the work behind a plan that extends a regression-test suite so it also notices what it is not catching and files new work for itself when it does. (A regression-test suite is the standing set of automated checks a project runs to confirm that yesterday's fix did not break today's feature.)

Moves the gloss out of the main sentence and lets the verbs do their job.

---

### P2. "What the plan does, in plain English" paragraph carries three ideas

**Before (Introduction, ¶2):**
> The plan installs three background processes ("watchers") that share custody of a project's quality. One watches for new bugs and coverage gaps by running the existing regression tests on a schedule. Two more drive the resulting work — one for bug fixes, one for user-experience improvements — through a reproduce-fix-verify cycle, with a separate review step that grades each candidate change. A "scenario quality supervisor" sits between the review step and merge to check that the review itself was thorough enough. A capstone evaluation wraps the whole thing: a single-prompt task with real internet access, followed by an audit that walks the agent's transcript to verify it did not just look the answer up online.

The paragraph topic-sentences three watchers and then adds a supervisor and a capstone, so the opening promise of "three" undersells the actual structure. The reader gets to sentence four and silently revises the count.

**After:** split into two paragraphs.
> The plan installs three background processes ("watchers") that share custody of a project's quality. The first watches for new bugs and coverage gaps by running the regression tests on a schedule. The other two drive the resulting work — one for bug fixes, one for user-experience improvements — through a reproduce-fix-verify cycle, with a separate review step that grades each candidate change.
>
> Two evaluators sit on top. A "scenario quality supervisor" checks that the review step itself was thorough enough before a change is allowed to merge. A capstone evaluation closes the loop: a single-prompt task with real internet access, followed by an audit that walks the agent's transcript to verify the agent did the work rather than searching for the answer online.

---

### P3. Section 1 opening conflates three eras with one historical claim

**Before (§1, ¶1):**
> If you want to know whether a coding assistant is any good, you need a test it hasn't already seen the answer to. The history of those tests has three eras, and the plan's capstone evaluation (the final pull request in the plan — an automated agent has to complete a realistic engineering task under a written directive, with real internet access, and an audit afterward decides whether the agent actually did the work or cheated) sits in the third.

The second sentence runs 51 words and uses an em-dash parenthetical so long the reader loses the "sits in the third" payoff. The capstone definition is already in the Introduction and the Appendix.

**After:**
> If you want to know whether a coding assistant is any good, you need a test it has not already seen the answer to. The history of those tests has three eras. The plan's capstone evaluation sits in the third.

The redundant gloss can go; the term is glossed twice already.

---

### P4. §1, ¶2 (HumanEval/MBPP) — paragraph carries two ideas

**Before:**
> The first generation, **HumanEval** (...) and **MBPP** (...), evaluated a model on isolated function-completion problems — write a single function to match a docstring — graded by hidden tests: small automated checks (called unit tests) that run a function and confirm it produced the right output. "Hidden" means the candidate doesn't see them, so they can't be gamed. These benchmarks range from a couple hundred to a couple thousand tasks; HumanEval at 164 tasks is the smallest of the modern set, SWE-Bench at roughly 2,300 is the largest. HumanEval and MBPP were the right benchmarks for their era. They tell you almost nothing about a system that has to live inside a real codebase. They were also rapidly contaminated...

The "range from a couple hundred to a couple thousand" sentence does not belong here — it is a cross-benchmark comparison dropped into a first-generation paragraph. The sentence about SWE-Bench's size is forward-referencing material from later in the section.

**After:** delete the sizes sentence. It is decoration, not argument, and SWE-Bench's 2,294 tasks are mentioned in the next paragraph anyway. The paragraph then carries one idea: what the first generation tested and why it stopped being useful.

---

### P5. §3.1 last paragraph — two ideas welded together

**Before:**
> What the plan does materially differently from CodaMosa or Fuzz4All is the *durability* of the generated tests. Both produce throwaway suites for the run at hand. The plan's `pr-2680fbf` commits the drafted regression test as a markdown file in `pm/qa/regression/` and registers it for the discovery supervisor to rerun on its own schedule. Each QA run that hits a new surface deposits a durable artifact. The closest analog in the literature is not so much a paper as it is the idea behind continuous fuzzing infrastructure like **OSS-Fuzz** (...) The discipline OSS-Fuzz illustrates is that "durable" earns its keep when measured: bugs found per week, corpus size growth. The plan inherits the design pattern; whether it inherits the measurement discipline is taken up in the Conclusion. Whether durable tests *compound* — produce more value per cycle than the cycle before — is a separate, stronger question taken up in the Conclusion, where the measurement obligations are listed.

The last two sentences both say "taken up in the Conclusion." Pick one.

**After:** end the paragraph with:
> The plan inherits the design pattern. Whether it also inherits the measurement discipline — and whether durable tests *compound* rather than merely accumulate — is the question the Conclusion takes up.

---

### P6. §5 self-correction-rebuttal paragraph runs 11 sentences

**Before:**
> The plan's loops are not intrinsic self-correction. Each iteration generates new artifacts — regression test files, evidence captures, tool-use transcripts, coverage reports — that are external to the model's reasoning and checked by mechanical systems. The LLM is acting as a generator of legible, checkable data, not as a reasoner improving in a vacuum. The scenario quality supervisor (...) examines the scenario session's tool-use transcript and captured outputs — external data — not its own reasoning trace. The bug-fix flow (...) requires a failing test that demonstrates the bug before any fix is attempted — external grounding. The capstone integrity audit (...) walks the agent's actual tool calls against an allowlist — external check. The coverage gates (...) measure code execution, not model self-assessment. Huang et al.'s result still applies as a caution, but the bound matters: the plan is in the regime where self-correction-with-external-feedback works, not the regime where it degrades.

The middle four sentences are a list dressed up as prose ("X — external data," "Y — external grounding," "Z — external check"). The rhythm gets dull and the dashes start to feel like a tic.

**After:**
> The plan's loops are not intrinsic self-correction. Each iteration produces new artifacts — regression-test files, evidence captures, tool-use transcripts, coverage reports — that mechanical systems check independently of the model's reasoning. Concretely: the scenario quality supervisor reads the scenario's tool-use transcript, not its reasoning trace (`pr-98f670e`); the bug-fix flow refuses to attempt a fix until a failing test demonstrates the bug (`pr-30588a7`); the capstone audit walks the agent's tool calls against an allowlist (`pr-e2b7fdf`); the coverage gates measure code execution rather than model self-assessment (`pr-b42059d`, `pr-8ed578d`). Huang et al.'s caution still applies, but the bound matters: the plan operates where self-correction-with-external-feedback works, not where it degrades.

Same content, half the dashes, parallel structure earned rather than imposed.

---

### P7. §6.1 (Pretraining contamination) paragraph stitches four ideas

This paragraph runs Sainz → Riddell → EvalPlus → surveys without transitions. The EvalPlus aside ("a different failure mode but rhymes with pretraining contamination") is genuinely a tangent in a paragraph that is already trying to do too much.

**Before:** one nine-sentence paragraph.

**After:** split at "EvalPlus." Move the EvalPlus sentence into a one-sentence bridge paragraph between §6.1 and §6.2, or cut it (it is already mentioned in §1).

---

## Sentence-level findings

### S1. "sits in" tic

`sits in`, `sits between`, `sits on top of`, `sits at`, `sits in this sub-genre`. Count: at least eight occurrences. The verb has become wallpaper.

**Cuts/rewrites:**
- "The plan's capstone evaluation … sits in the third" → "belongs in the third"
- "A 'scenario quality supervisor' sits between the review step and merge" → "stands between the review step and merge"
- "Two evaluators sit on top" → "Two evaluators close the loop"
- "The plan's scenario quality supervisor sits in this sub-genre" → "The scenario quality supervisor belongs to this sub-genre"
- "The autonomous regression and bug-fix loop sits at a multi-way intersection" → "draws on several research areas at once"
- "The plan sits in the upper-right quadrant" → keep one; this is where the metaphor earns its keep.

### S2. "is doing the same job" / "is doing the same thing"

Three near-identical sentences:
- §3.1: "The plan's coverage-driven scenario growth (`pr-c2397e2`) does the same thing at a higher level of granularity."
- §3.1: "the plan's `pr-2680fbf` and `pr-51586d2` … are doing the same thing one level higher."
- §4: "The plan's bug-fix flow is doing the same job APR has been doing for a decade."

**Rewrites:**
- "applies the same coverage-feedback pattern at a coarser grain"
- "lift the same pattern to the regression-suite level"
- "The plan's bug-fix flow re-runs APR's decade-old playbook with a new generation mechanism."

### S3. Buried subject in capstone-defense sentence

**Before (§6.2):**
> The audit has a hard problem because: the sandbox lets the agent reach the open internet (...); the agent has reason to peek at how others solved the same problem; the run is long enough that one stray click can taint everything that follows; the trace shows every action but doesn't label any of them as cheating; and the grader only looks at the final answer, where a cheated and a legitimate solution look identical.

A colon after "because" introducing a five-item semicolon list is grammatically loose and reads as a slide bullet. Five reasons read aloud as one breath defeats the reader.

**After:**
> The audit faces a hard problem on five fronts. The sandbox lets the agent reach the open internet, because otherwise the test is not realistic. The agent has reason to peek at how others solved the same problem. A single stray click can taint everything that follows. The trace records every action but labels none of them as cheating. And the grader sees only the final answer, where a cheated solution and a legitimate one look identical.

### S4. Run-on with three "and"s

**Before (§7, ¶1):**
> a polling background process that periodically scans a known surface, files PRs as it finds work, and lets the human-or-automation merge gate decide what ships.

`human-or-automation` is a hyphen-compound asking too much. Rewrite:

**After:**
> a polling background process that scans a known surface, files PRs as it finds work, and leaves the merge decision to whatever gate — human or automated — already exists.

### S5. Sentence-internal logic inversion in §2 conclusion

**Before:**
> The plan reuses Claude Code as the underlying agent for every watcher tick, so the relevant architectural insight is less "how do we build an agent?" and more "how do we shape its surface."

The load-bearing claim is the second half; the first half is throwaway setup. As written, the throwaway is the main clause.

**After:**
> Because the plan reuses Claude Code as the underlying agent for every watcher tick, the architectural question is not "how do we build an agent?" but "how do we shape its surface?"

### S6. "Qualitatively consistent with" non-sentence

**Before (§6.2):**
> Qualitatively consistent with the formal characterizations in Skalse 2022 and Pan 2022: see also METR's 2025 informal report on reward-hacking in frontier models, an industry source consistent with the formal characterizations above (Von Arx, Chan, Barnes, metr.org/blog/2025-06-05-recent-reward-hacking/).

Not a sentence. The phrase "consistent with the formal characterizations" appears twice in one breath. The colon after a non-clause is broken.

**After:**
> METR's 2025 industry report on reward-hacking in frontier models (Von Arx, Chan, Barnes) is qualitatively consistent with Skalse 2022 and Pan 2022, though informal.

### S7. Section 7's "honest summary up front" tic

**Before:**
> The plan's three watchers look a lot like Dependabot. Here's what is and isn't borrowed, and where the plan diverges. The honest summary up front: this is industry-dominated territory; the strongest peers are industry products, the academic adjacencies are real but thinner.

Three sentences, three voices: declarative, signposting, table-setting. "Honest summary up front" is a tic ("the honest negative result" appears in §3.2 too).

**After:**
> The plan's three watchers look a lot like Dependabot. The closest peers here are industry products; the academic adjacencies are real but thinner. This section maps what the plan borrows and where it diverges.

---

## Word-level findings

### W1. Vague verbs

- "the plan **does** materially different work" (Conclusion, twice in §3.1) — replace with "departs," "breaks with," "diverges."
- "what the plan **does** in plain English" — keep, since this is a heading-style cue.
- "the plan's situation **is** structurally different" (§6.2) — "differs structurally."
- "what they **get** from reading this section" — fine.
- "are doing the same job" — see S2.
- "have to be inferred from" (§2, Devin) — "have to be inferred from" is correct but the next clause is a colon-list; reads better as "must be inferred from the product surface, which offers..."

### W2. "substantial" / "substantially" overuse

Count: 7+ occurrences. "substantial pre-LLM literature," "substantial 2023-vintage academic literature," "substantial fraction," "substantially outperforms," "substantially richer policy control," "a substantial follow-up empirical literature."

The word has become filler. Cuts:
- "substantial pre-LLM literature" → "long pre-LLM literature"
- "substantial fraction" → "sizeable fraction" or just "a fifth to nearly a third" (the number is right there)
- "substantially outperforms" → "outperforms"
- "substantially richer policy control" → "richer policy control"
- "a substantial follow-up empirical literature" → "a follow-up empirical literature"

### W3. "materially" tic

"materially differently," "materially different work," "the materially different choice the plan makes." Three uses of "material/materially" in the load-bearing comparison sentences. Replace with concrete verbs:
- "What the plan **does materially differently** from CodaMosa or Fuzz4All is the *durability*..." → "**Where the plan departs from** CodaMosa and Fuzz4All is on **durability**."
- "Where the plan **does materially different work**: regression tests are durable..." → "Where the plan **departs from prior work**: regression tests are durable..."
- "The **materially different choice the plan makes is** *dynamic prioritization...*" → "The plan's distinctive choice is **dynamic prioritization without persisted structured priority**."

### W4. "load-bearing" overload

Five occurrences. The methodology file uses the phrase as a term of art and it has bled into the prose. In the lit review proper it should appear once at most.
- "the load-bearing rebuttal" (§5)
- "the load-bearing literature for the capstone PR" (§6 opener)
- "the most under-validated mitigation" — fine
- "the load-bearing claim" — not in the lit review; this is in the methodology
- "load-bearing prose" — methodology

Keep §6's "load-bearing literature for the capstone PR" because it is doing real work (signaling priority). Cut "the load-bearing rebuttal" — say "the sharpest rebuttal" or "the strongest counter."

### W5. "in short" / "in the spirit of" / "in plain English"

- "In short: NIST is the one direct precedent." Fine here — it actually summarises.
- "in the spirit of SWE-agent's ACI argument" (Conclusion) — fine.
- "What the plan does, in plain English." — fine as a section-cue.

These are not problems; flagging only because the surface shape resembles deadwood elsewhere.

### W6. "the plan" repetition

The phrase "the plan" appears ~80 times. In a long-form review of a single plan this is unavoidable, but four cases stack three "the plan" in adjacent sentences (Conclusion ¶2). Some can be "it" or "the design":
- "The plan's bug-fix flow is doing the same job APR has been doing for a decade. The generation mechanism has changed (genetic programming → LLM), but the surrounding flow is the closest academic analog the plan has." → second instance: "the closest academic analog the design has."

### W7. "rough" precision

- "the surrounding flow" (§4) — what does "surrounding" mean here? The structural flow? The control flow? Better: "the surrounding loop" or "the orchestration around the generation step."
- "the surface" used to mean three different things — "review surface," "uncovered surface," "watcher's surface," "product surface." Each is correct in isolation but the reader has to re-anchor each time. Where possible, swap to the specific noun: "uncovered code," "the product itself," "the watcher's prompt and tool menu."

---

## Voice and tone

### V1. Slip into casual second person

The document is mostly third-person, observational. Two slips:
- §1 ¶1: "If you want to know whether a coding assistant is any good, you need a test it hasn't already seen the answer to."
- §1 ¶2: "They tell you almost nothing about a system that has to live inside a real codebase."

These are both deliberate hooks and the second-person works in the section opener. The second slip ("tell you almost nothing") in the next paragraph reads as a hangover. Pick one:

**After:**
> They reveal almost nothing about a system that has to live inside a real codebase.

### V2. "Here's" colloquialism mid-document

§7: "Here's what is and isn't borrowed." — see S7 rewrite. The contraction is fine in the introduction, but by §7 the register has settled into something more sober and "here's" sticks out.

### V3. "If the plan succeeds, the capstone is the most distinctive thing it will have shown; if it fails, it is the most likely point of failure."

Conclusion ¶2. Strong sentence. Keep. Flagging only as the example of voice at its best — every other Conclusion sentence should aim at this clarity.

### V4. Methodology-speak leaking in

"under-validated mitigation," "measurement obligations," "verdict surface," "structured artifact." These are jargon-ish but acceptable in this register. However "the contamination-defense axis, read top to bottom" reads like reviewer prose, not author prose:

**Before:** "The contamination-defense axis, read top to bottom, runs from no defense at all to detecting cheating after the fact:"

**After:** "Reading the rows top to bottom: defenses get stronger from no defense at all to post-hoc detection."

---

## Emphasis and modifiers

### E1. Italics audit

Italicized phrases (sample, not exhaustive):
- *notices* (Intro) — unearned; the surrounding clause already signals novelty.
- *pretraining contamination*, *runtime contamination* (Intro) — earned; these are coined contrast terms.
- *how realistic is the task*, *what does the benchmark do…* (§1) — earned; they label axes.
- *durability* (§3.1) — earned, single use.
- *intrinsic self-correction* (§5) — earned; defines a term.
- *verbal reinforcement learning* (§5) — earned.
- *process supervision* (§5) — earned.
- *attempts* (§5, "*attempts* to reduce shared context") — unearned. The qualifier already does the work. Cut italics.
- *What `--resume` actually shares is a material detail.* (§5) — italics on a complete sentence is heavy-handed. Bold or nothing.
- *post-run integrity audit* (§1) — earned.
- *use the LLM as the escape valve…* (§3.1) — earned (callout phrase).
- *rebuild* (§1) — earned, single word.
- *sufficient* (§3.1) — fine.
- *compound* (§3.1, Conclusion) — earned.
- *denies* / *grants* (§1) — earned (contrast pair).
- *during the run* (§6.2) — earned (key time-anchor).
- *dynamic prioritization without persisted structured priority* (§7) — earned.
- *structured* (§7) — fine.

**Cuts:** italics on *notices*, *attempts*, and the full sentence *What `--resume` actually shares is a material detail.*

### E2. Bold audit

Bold is used for author/work names (canonical references) and one or two emphasis sentences. The author-name bolding is consistent and helpful. Bold on *What `--resume` actually shares is a material detail* is the only sentence-level bold and clashes with the convention. Demote to plain text and rely on sentence position.

### E3. Em-dash density

Some paragraphs use three or four em-dashes (§5 paragraph in finding P6 has six). Em-dash is the review's default punctuation for parenthetical material; that is fine, but where the same paragraph stacks three or more, swap one or two for commas or parentheses. Specific candidates:
- §1 ¶2: "graded by hidden tests: small automated checks (called unit tests) that run a function..." — the colon plus parenthesis plus em-dashes earlier in the sentence is too much. Rewrite as two sentences.
- §3.1 ¶3 ("CodaMosa is the seminal paper..."): four em-dashes. Convert one to parens.

### E4. Intensifiers

- "much harder task and a much more realistic one" (§1) — drop one "much."
- "the right benchmarks for their era" — fine.
- "rapidly contaminated" — fine.
- "deliberately-minimal scaffold" — drop "deliberately"; minimal is enough.
- "sharply skeptical 2023-2024 follow-up literature" — keep; the contrast does work.
- "tightly-scoped job" — keep.
- "categorically different defenses" — keep.

### E5. Hedging

The doc is mostly clean on this front, but:
- "may shift" (§6.3 Anthropic) — keep, this is a real uncertainty about a non-peer-reviewed source.
- "some specific claims may shift" — fine.
- "could be either easier … or harder" (§6.3, ImpossibleBench) — fine, this is the actual open question.
- "tends to drift" (§7) — the field this modifies is "structured priority"; the hedge earns its place.
- "The audit has a hard problem because..." (§6.2) — fine.

No unearned hedges of significance. Solid here.

---

## Clichés and deadwood

### C1. Clichés

- "shares custody of a project's quality" (Intro) — "shares custody" is metaphor; works. Keep.
- "draw on" / "draws on" — fine.
- "the inner clock of a continuous quality loop" (Conclusion) — strong, keep.
- "no analogous numbers exist for runtime-internet lookup detection" — fine.
- "the closest peer in the literature" — used three times. Once is sharp; thrice is a formula. Vary:
  - "the closest peer in the literature to the plan's three-watcher structure" (§2) → "the literature's nearest match"
  - "the most direct missing peer" (§3.1) → keep
  - "the published analog to the watcher review session" (§7) → keep
  - "the closest neighbor in the literature is not so much a paper as it is the idea behind continuous fuzzing infrastructure" (§3.1) → "the nearest analog is not a paper but the idea behind OSS-Fuzz"

### C2. Deadwood / bloat

- "for the run at hand" (§3.1) → "for that run"
- "in roughly the order the plan would encounter it" (Intro) → "in roughly plan order"
- "Each is also glossed inline at first body use." (Appendix preamble) — already said in Intro. Cut one.
- "is more portable than the specific instantiation" (§3.1) → "is more portable than CodaMosa itself"
- "is structurally similar to Self-Debug … but the plan's bug-fix watcher operates at the watcher-tick level" (§4) — "but operates at the watcher-tick level" is enough.
- "the literature does not speak to this design directly; it is the plan's most distinctive structural commitment" (§7) — two sentences for one idea. Compress: "The literature offers no direct precedent for this commitment, which is the plan's most distinctive structural choice."
- "**Important**: for every Block 4 finding..." — methodology language; not in lit review proper. Skip.

### C3. Phrasings that survive on familiarity

- "the contamination question runs through all of them in two different forms" (Intro) — "in two different forms" can lose "different."
- "the design space is broader than the SWE-agent / OpenHands lineage" (§2) — fine.
- "the practitioner-facing analogs to one another" — "the practitioner-facing analogs of each other" or just "practitioner-facing peers."
- "more readily when the generator and the evaluator share context" (§5) — fine.
- "the design pattern" / "the same shape" / "the same pattern" — "shape" is used 9+ times. Rotate: "form," "architecture," "scaffold," "skeleton."

---

## Overall verdict

The prose is in good shape for an artifact at this stage. The voice is mostly consistent (a serious essay register with controlled informal hooks), the metaphors are working (custody, inner clock, blueprint, chassis), and the hedging is calibrated against real uncertainty rather than reflexive. The strongest passages are the §1 axis paragraph, the §6.2 threat-model framing, and the Conclusion's "if it succeeds / if it fails" sentence. The weakest are the dash-heavy paragraphs in §5 (P6), the colon-list pseudo-sentence in §6.2 (S3), and three or four tic-words ("sits," "substantial," "materially") that recur enough to register. A single copy-edit pass focused on (a) cutting two-thirds of the "substantial / materially / sits" occurrences, (b) splitting P6 and the §6.1 paragraph, (c) restoring the sentence-form to S3 and S6, and (d) auditing em-dash density paragraph by paragraph would lift the document from "well-written for an internal review" to "polished enough for external readers." A second pass is not warranted; the issues are surface-level and the substance underneath is sound.
