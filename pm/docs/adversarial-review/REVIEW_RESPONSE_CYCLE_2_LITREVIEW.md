# Review Response — Cycle 2 (literature-review.md)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_2_LITREVIEW.md`

Cycle 2 is sharper than Cycle 1 and lands several findings that directly rebut moves we made during Cycle 1's response. We accept most. The remaining work falls into three buckets: (a) take the rebuttals seriously and rewrite the contested framings, (b) execute the Block 2 structural fixes, (c) do the Block 3 accessibility work in earnest — which is the bulk of the second-pass edit.

## Bucket A — substantive rebuttals (Block 1)

### A1. §5.3 three-axes framing — agree, rewrite to a single-peer honest framing

**Agree.** The "NIST on threat model, Anthropic on supervisor architecture, ImpossibleBench on empirical" framing was a rhetorical move to preserve the "three thin peers" novelty story, and the reviewer is right that NIST does double duty.

**Edit**: rewrite §5.3 as: "NIST CAISI's transcript-review work is the closest direct precedent for the audit, on both the threat model (catching agents that consult forbidden materials at runtime) and the audit architecture (walk a transcript, check against an allowlist, emit a structured artifact). Anthropic's alignment-auditing-agents work is adjacent on the supervisor-architecture axis but addresses a different problem (alignment evaluation, not cheating detection during evaluations). ImpossibleBench measures cheating propensity in coding agents but the published sensitivity numbers (42-50% on complex cases, 86-89% on simpler ones) are for test-modification detection, not external-lookup detection — different cheats with different signatures. We cite ImpossibleBench because no published number for lookup-detection sensitivity exists at the time of writing, but the reader should treat it as a suggestive anchor for the LLM-as-monitor problem in general, not as a direct empirical floor for the audit."

The novelty story shrinks accordingly. That is fine — the novelty was over-claimed.

### A2. Pan et al. "context separation" overreach — agree, replace with a weaker, honest claim

**Agree.** The Cycle 1 response wrote "is exactly Pan et al.'s recommended mitigation" without verifying Pan et al. actually prescribed separation. The reviewer's read of the abstract is correct: Pan et al. identify context-sharing as a factor, they do not prescribe separation as the mitigation. The response put words in the source's mouth.

**Edit**: rewrite §4's Pan et al. passage to: "Pan et al. 2024 study iterative self-refinement and find that *spontaneous reward hacking* emerges more readily when the generator and the evaluator share context. The plan's QA scenario quality supervisor (`pr-98f670e`) attempts to reduce that shared context by running the supervisor as a separate session that reads the scenario's captures and tool-use transcript via Claude Code's `--resume` mechanism rather than running inside the scenario's loop. **What `--resume` actually shares is a load-bearing detail.** It carries forward the session's accumulated state — system prompt, prior turns, tool-use history. It does *not* run as the same continuous reasoning process. The exact degree to which this counts as 'context separation' in Pan et al.'s sense is unsettled; a fully separate model or a fresh session with only the captured artifacts as input would be stronger. The amendment cap (default 2) is the primary mitigation; the `--resume` arrangement is a secondary reduction of shared context that has not been independently validated."

**Action item for the plan**: the response should also flag this back to the plan's owner — `pr-98f670e`'s description should be updated to state what `--resume` carries and what an even-stronger version would look like (fresh session, captures-only input). We will note this in the response's tail "items to surface to the plan" section.

### A3. §6 merge is renaming, not consolidation — agree, restructure

**Agree.** The reviewer is correct that merging §6 and §7 didn't fix the underlying density problem. The proposed restructuring is sensible:

- Move §6.2 (Automated program repair in CI) next to §3 (test generation). The bug-fix flow conceptually mirrors the test-generation pipeline (test-then-repair), and APR's peers naturally sit alongside test-generation peers.
- Demote §6.3 (Fakes and test doubles for LLM-and-VCS code) to a paragraph in §6.1 or to a parenthetical note in §3, framed as "an honest negative result on the academic search."
- Rename §6 to "Watcher Architectures (industry-dominated)" — drop the "Operational Infrastructure" framing that was trying to make the merge look principled.

**Edit**: restructure as described.

### A4. "Compounding regression library" still unmeasured — agree, downgrade to "durable" or define the metric

**Agree.** The reviewer is right that "compounding" is doing aspirational work the design hasn't earned with a target. Two acceptable resolutions:

1. Replace "compounding" with "durable" (the weaker, defensible claim: regression tests authored once persist on the project branch and the discovery supervisor reruns them on schedule).
2. Keep "compounding" and define the metric inline: "compounding — measured here as net growth in regression-test count over time, coverage delta per scenario, and bug-recurrence rate. These metrics are not yet collected in `pm`; defining them and reporting them is a follow-up the plan owes."

**Edit**: go with (1) for the §3 instance ("durable") and (2) for the Conclusion (so the reader knows what compounding would mean if claimed). This pattern — strong claim with named metric, weak claim where the metric isn't yet collected — is the discipline OSS-Fuzz illustrates and the review correctly invokes.

### A5. §1 benchmark table is decoration — partial agreement, restructure rather than cut

**Partial agree.** The reviewer is right that "Evaluator" reads the same for 8 of 9 rows and "Network access" reads the same for 7 of 9. The table has informational redundancy.

But the table also lets a non-developer reader *see* the contamination-defense evolution in one glance, which is hard to extract from prose. The reviewer's alternative — a 2D plot of "contamination-defense strength × task realism" with the capstone plotted — is genuinely better.

**Edit**: replace the existing table with a 2D ASCII placement plot. Axes: contamination defense (none → human-filter → time-window → cleanroom) on one axis, task realism (function-completion → real-issue-on-real-repo → rebuild-from-binary) on the other. Plot the same nine benchmarks plus the plan's capstone. Keep a one-paragraph caption describing the trajectory the field has taken across both axes.

### A6. ASCII diagrams — agree, cut the §4 one and keep the §6 one with a better axis label

**Agree.** The §4 self-critique evolution diagram restates the prose with arrows and adds nothing. Cut.

The §6 2x2 quadrant works. The reviewer flags the "online vs offline" axis label as overloaded (in software the phrase can mean "live network access" or "real-time vs batch processing"). Relabel to "live internet access" vs "snapshot benchmark."

**Edit**: cut §4 diagram; relabel §6 quadrant axes.

### A7. Citation graph walk perfunctory — agree, do a tighter follow-up

**Agree.** The walk surfaced first-page-of-arxiv-sanity results, not graph-traversal results. The reviewer names specific missing references that a real walk would have caught.

**Edit**: add the named missing references with one-line characterizations and a sentence on relevance to a specific plan PR:

- **Chen et al. 2023 "Teaching Large Language Models to Self-Debug"** (arXiv:2304.05128) — bridges §4 (self-refinement) and §3 (test feedback). Adds to §4: the plan's bug-fix flow (`pr-30588a7`) is structurally a self-debug loop with the test as the external feedback signal.
- **Mündler et al. 2024 "SWT-Bench"** (arXiv:2406.12952) — LLMs generating tests rather than fixing bugs. Direct peer for `pr-2680fbf` (planner authors a new regression). Adds to §3.
- **Zheng et al. 2023 "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena"** (NeurIPS 2023) — foundational for any LLM-as-evaluator pipeline. Adds to §5: relevant to the integrity audit's design and to the scenario quality supervisor.
- **Jain et al. 2024 R2E / R2E-Eval** — repository-level test generation with executable feedback. Adds to §3.
- **Zhang et al. 2023 "Self-Edit"** (ACL 2023) — code generation with execution-result feedback. Adds to §4.

Acknowledge in the Conclusion that the second-pass walk was also budgeted but caught the most-obvious missing peers.

### A8. ProgramBench asymmetry of evidence — agree, disclose

**Agree.** ProgramBench is currently treated as a peer to SWE-Bench when its evidence base is much weaker (a website snapshot and a recent preprint vs. SWE-Bench's ICLR publication and extensive follow-up literature). The review owes the reader that disclosure.

**Edit**: add a sentence to ProgramBench's first mention in §1: "ProgramBench is much newer than SWE-Bench and its evidence base is correspondingly thinner — it is cited here based on its website (programbench.com, snapshot 2026-05-14) and an arXiv preprint (2605.03546). It does not yet have the follow-up literature SWE-Bench has accumulated, and the reader should weight claims about ProgramBench's design accordingly."

This also defangs §6's quadrant placement of ProgramBench, which currently assumes the design is settled.

### A9. METR over-cited — agree, bracket the citation

**Agree.** METR's reward-hacking report is a blog post in a research-org's outreach channel, and the cited behaviors are from a different benchmark (RE-Bench, ML-research-engineering tasks) than the capstone (code-and-internet). The review presents it as load-bearing for §5.2; that's a stretch.

**Edit**: bracket METR as a suggestive industry signal rather than load-bearing data. Add a peer-reviewed alternative — **Skalse et al. 2022 "Defining and Characterizing Reward Hacking"** (NeurIPS 2022) and **Pan et al. 2022 "The Effects of Reward Misspecification"** — and frame METR as "qualitative recent observations consistent with the formal characterizations in Skalse and Pan."

### A10. Numbered references in Conclusion don't match prose — agree, fix

**Agree.** This is exactly the kind of partial edit a Cycle 2 reviewer should catch. The numbered list and the parenthetical numbering desync was caused by adding references after the list was first drafted.

**Edit**: either renumber both consistently or drop the numbered indices and let the prose name papers by author.

## Bucket B — structural and readability fixes (Block 2)

### B1. Introduction is dense and front-loads jargon

**Agree wholesale.** The reviewer's proposed replacement opener is good. Use a variant of it: introduce the plan's goal in plain English first, then the watcher / supervisor / capstone vocabulary one term at a time.

**Edit**: rewrite the Introduction's opening paragraph following the reviewer's proposed shape, with each new term glossed inline on first use.

### B2. §1 opening — agree, use the reviewer's proposed hook

**Edit**: replace §1's opener with: "If you want to know whether a coding assistant is any good, you need a test it hasn't already seen the answer to. The history of those tests has three eras, and the plan's capstone evaluation sits in the third."

### B3. §5 signposting — agree, use the threat-surface list as a spine for §5.3

**Edit**: restructure §5.3 so each peer's relevance is framed against a specific threat-surface item. Either (a) for each peer, explicitly name which items it addresses, or (b) inline the threat-surface items into the §5.3 narrative and cut the standalone list.

### B4. Bridges are weak — agree, rewrite

**Edit**: rewrite both bridges. §4→§5: "Self-improvement loops trust the model's own grade. What if the model could just look up the answer? §5 surveys the literature on catching that." §5→§6: "§5's audit is an operation that happens once per task run. §6 surveys how others have built systems that run such operations on a continuous cadence."

### B5. Huang/Pan defense repeated three times — agree, consolidate

**Edit**: keep the full statement in §4. Reference it briefly in §5 and the Conclusion ("as discussed in §4..." with a one-clause restatement). Cut the ASCII timeline since A6 already removes it.

### B6. Conclusion "ten seed references" + "citation-graph walk" overlap — agree, merge

**Edit**: combine into a single passage: "Ten seed papers cover roughly the substantive lineage: benchmarks (Jimenez 2024, Yang 2024), self-improvement (Madaan 2023, Shinn 2023, Huang 2023), contamination and cheating (Sainz 2023, Riddell 2024, Zhong 2025), and the test-generation primitive (Lemieux 2023). A budgeted citation-graph follow-up added Pan 2024, Agentless, AutoCodeRover, AgentSpec, AgentAuditor, the Anthropic auditing-agents work, TestPilot, EvalPlus, SapFix, GenProg, SWE-Bench Multimodal, Chen 2023 self-debug, Mündler 2024 SWT-Bench, Zheng 2023 LLM-as-Judge, Jain 2024 R2E, and Zhang 2023 Self-Edit. The walk remains under-budgeted for a full traversal; readers chasing a specific thread should treat this as a starting set, not a complete one."

### B7. References section needs peer-reviewed / preprint / industry split — agree

**Edit**: split into three labeled subsections in the references list. Move arXiv-only preprints out of the "Peer-reviewed" category. Keep the "Industry references" section as the third subsection and rename to "Industry and non-peer-reviewed."

## Bucket C — Block 3 accessibility work (the bulk of the second pass)

The reviewer wrote out 30+ specific glosses with proposed inline text and rewrote section openers. **This is the deliverable.** We accept all of it modulo minor judgment calls.

### Approach

Rather than treat each glossing as a separate decision, we adopt a single policy and apply it everywhere:

> **First use of any jargon term — software-engineering, tool-name, research-vocabulary, or acronym — gets an inline gloss in a parenthetical or a comma-separated apposition.** The gloss uses target-reader vocabulary (no nested jargon). On second and later uses, the term appears alone.

Then we work the reviewer's list as the punch list.

### Glossings accepted (all of §3.1-§3.5)

All accepted. Edits apply the reviewer's exact proposed glosses where they pass the "no nested jargon" test, and a minor rewrite where they don't. The cases the reviewer flagged as needing a second pass (e.g., `actor-critic` gloss using `implementation watcher` which is itself project jargon) we address by:

1. Adding glosses for *project* terms early in the document (`implementation watcher`, `QA review loop`, `watcher`, `the loop`, `discovery supervisor`, `capstone`, `auto-sequence`).
2. Using those glossed project terms freely in later glosses.

This creates a small "glossary spine" the rest of the document leans on.

### Section openers (§3.9) — all accepted

Use the reviewer's proposed openers verbatim, with minor tweaks to ensure each opener doesn't itself introduce new jargon.

### Scale anchors (§3.6) — all accepted

The pattern is consistent across the seven flagged numbers: state the metric, then the plain-English consequence ("monitor sensitivity of 42-50%" → "the monitor catches the cheat 42 to 50 percent of the time — roughly a coin flip"). Apply uniformly.

### Unmotivated framings (§3.7) — all accepted with the reviewer's proposed rewrites

The "biggest research bet" → "if the plan succeeds..." pattern is good; use it. Same for "offline benchmarks" and "stale priority field."

### Dense paragraphs (§3.8) — all four splits accepted

### Insider quips (§3.10) — agree, cut

"The honest assessment," "the walk was deliberately budgeted," "as discussed," "as we'll see" — all cut.

## Items to surface to the plan owner (out of scope for the lit review itself)

The Cycle 2 review's findings imply two things the plan should change, separate from the lit review's edits:

1. **`pr-98f670e`'s description should specify what `--resume` carries forward.** The lit review's "context separation" claim was overreach because the plan itself doesn't pin down what `--resume` actually shares. The plan's owner should add a "Implementation note on `--resume`" subsection to `pr-98f670e` clarifying which session state crosses into the supervisor and which does not. If the answer is "most of it," the design should be reconsidered — a fresh-session-with-captures-only variant is the stronger version of the mitigation.

2. **The "compounding regression library" claim should have a measurement plan attached.** If the plan claims compounding as a payoff, the plan should specify the metric (regression count over time, coverage delta per scenario, bug recurrence rate) and commit to collecting it as part of the discovery supervisor's work-log. We have downgraded the lit review's framing to "durable" but the plan can earn back the stronger claim with the measurement plan in place.

Both items belong in `pm pr note add` entries on the relevant PR ids, not in the lit review.

## Edits checklist

Before any text changes land in `literature-review.md`:

1. Rewrite §5.3 to drop the three-axes framing; NIST is the closest peer on threat model and architecture; ImpossibleBench cited as "best-available proxy, different cheat type."
2. Rewrite §4's Pan et al. passage to acknowledge the source identifies context-sharing as a factor (not prescribe separation as the mitigation), and to flag `--resume`'s context-sharing as an unsettled question.
3. Restructure §6: move §6.2 (APR) next to §3; demote §6.3 to a paragraph; rename §6 to "Watcher Architectures (industry-dominated)."
4. Replace "compounding" with "durable" in §3; in the Conclusion, keep "compounding" with an inline metric definition.
5. Replace §1 table with a 2D ASCII placement plot of contamination-defense × task-realism.
6. Cut §4 ASCII diagram. Relabel §6 quadrant axes ("live internet access" vs "snapshot benchmark").
7. Add the named missing references (Chen 2023 self-debug, Mündler 2024 SWT-Bench, Zheng 2023 LLM-as-Judge, Jain 2024 R2E, Zhang 2023 Self-Edit) with one-line characterizations per PR relevance.
8. Disclose ProgramBench's asymmetric evidence base on first mention.
9. Bracket METR; add Skalse 2022 and Pan 2022 as peer-reviewed alternatives.
10. Fix the numbered-references mismatch in the Conclusion.
11. Rewrite the Introduction opening per the reviewer's proposed shape.
12. Replace §1 opener with the reviewer's proposed hook.
13. Use the threat-surface list as a spine for §5.3 (or inline the items).
14. Rewrite both bridges (§4→§5, §5→§6).
15. Consolidate the Huang/Pan defense to §4 only; reference it briefly elsewhere.
16. Merge the Conclusion's two enumerative passages (ten seeds + citation walk).
17. Split the references list into peer-reviewed / preprint / industry subsections.
18. Establish a glossary spine early in the document: gloss `watcher`, `the loop`, `implementation watcher`, `QA review loop`, `discovery supervisor`, `capstone`, `auto-sequence`, `regression-test suite`, `pull request`, `merge`, `Claude` / `Claude Code`, `LLM`, `PR`, `QA`, `UX`, `CI` on first use, somewhere in the Introduction or §1.
19. Apply all §3.1 / §3.2 / §3.3 jargon glosses inline at first use.
20. Spell out all acronyms on first use per §3.4.
21. Add one-line context for every named work per §3.5.
22. Apply scale-anchor rewrites per §3.6.
23. Apply unmotivated-framing rewrites per §3.7.
24. Split the four dense paragraphs per §3.8.
25. Replace section openers per §3.9.
26. Cut insider quips per §3.10.

## Notes for Cycle 3

After applying these edits, Cycle 3 should expect:

- §5.3 will be cleaner but the "best-available proxy, different cheat type" framing is still doing rhetorical work — Cycle 3 should pressure-test whether citing ImpossibleBench at all is honest given the cheat-type mismatch.
- §4's `--resume` passage will be more honest but introduces a new unsettled question (what `--resume` actually shares). Cycle 3 should check whether that question is answered anywhere in the codebase that a reader could verify.
- The §6 restructuring will have moved APR. Cycle 3 should check whether the new placement actually improves coherence or just relocates the density problem.
- The glossing spine is a new artifact. Cycle 3 should verify it doesn't itself introduce nested jargon and that the glossed terms are used consistently throughout the document.
- The METR bracketing and the Skalse/Pan additions will introduce new peer-reviewed content; Cycle 3 should verify the new characterizations.
