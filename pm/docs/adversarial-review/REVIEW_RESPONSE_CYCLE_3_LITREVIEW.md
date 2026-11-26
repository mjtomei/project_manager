# Review Response — Cycle 3 (literature-review.md)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_3_LITREVIEW.md`

Cycle 3 reached convergence: the reviewer explicitly judges this the natural last cycle, with most remaining findings correctable in a single targeted edit. We accept that assessment. This response works through the ~25 findings, accepts almost all of them, then expands on B1-2 (the `--resume` problem) at length because the user has flagged it as load-bearing for the *plan*, not just the lit review.

## Bucket A — substantive (Block 1)

### A1. B1-1 ImpossibleBench "best-available proxy" still imports a generous prior — agree, drop the numbers

**Agree.** The Cycle 2 soften move went halfway. The reviewer is right that even the softer framing imports priors the data don't license: ImpossibleBench's cheat is *artifact-visible* (the patch contains the test modification), the capstone's cheat is *trace-visible-only* (the patch looks fine, the URL is in the transcript), and the task-solvability differs (ImpossibleBench tasks are unsolvable honestly, capstone tasks are).

**Edit**: drop the 76% / 42-50% / 86-89% numbers from §5.3. Replace with: "No analogous numbers exist for runtime-internet lookup detection. ImpossibleBench is cited as a structurally adjacent measurement effort, but its sensitivity figures are for test-modification (an artifact-visible cheat), not for external lookup (a trace-only cheat), and the proxy direction is unknown — lookup-detection could be either easier (URLs in the trace are distinctive) or harder (the artifact contains no fingerprint). The audit's sensitivity is an open question and a measurement obligation, not a known floor."

This honestly resets the empirical anchor.

### A2. B1-2 `--resume` defense reduces to the iteration cap — agree, expand to a design note

**Agree, expanded below.** See "Bucket D" at the bottom of this response, plus a separate plan-owner note at `pm/docs/adversarial-review/RESUME_DESIGN_NOTE.md`.

For the lit review itself: tighten §4's `--resume` passage to acknowledge that "amendment cap of 2 in a context-sharing regime is exactly the regime Pan et al. measured hacking in," and add a sentence to the Conclusion's "where the plan is making its own bet" section noting that `pr-98f670e`'s design is the most under-validated of the plan's mitigations.

### A3. B1-3 76% GPT-5 figure doesn't match — verify or drop

**Agree.** The reviewer's independent fetch of arXiv:2510.20270 found 54.0% on Conflicting-SWEbench (full scaffold) and 2.9% on Oneoff-LiveCodeBench, not 76%. Either pin the 76% to a specific table-and-cut in the paper, or drop the prose figure entirely.

**Edit**: drop the prose figure. Replace with the verified 54% number with citation to the specific section.

### A4. B1-4 Citation status upgrades — agree

**Edits**:
- OpenHands (Wang et al., arXiv:2407.16741): move from Preprints to Peer-reviewed; cite as "ICLR 2025 (Poster)."
- AgentAuditor (arXiv:2506.00641): confirmed NeurIPS 2025; promote from "preprint" to "NeurIPS 2025."
- Liars' Bench: update title to "Liars' Bench: Evaluating Lie Detectors for Language Models" (arXiv:2511.16035).

### A5. B1-5 Work-log smuggles priority state — agree, tighten language

**Agree.** The "no priority field stored anywhere" claim conflicts with the work-log carrying signals that re-bias priority. Honest tightening:

**Edit**: rewrite §6 line to: "no *structured* priority field; priority signals persist informally in the work-log and are re-weighted each tick." Mention that this is exactly the kind of state a structured priority field would normally hold, and that the plan's bet is that prose persistence + LLM re-weighting beats structured-field maintenance.

### A6. B1-6 Compounding metrics are loose — agree, commit or admit

**Agree, partial.** The reviewer correctly notes the three named metrics (regression-test count growth, coverage delta per scenario, bug-recurrence rate) each have problems: count is gameable, coverage diminishes, recurrence needs a denominator.

**Edit**: replace the loose metric list in the Conclusion with: "Operational definitions for 'compounding' would need to address: (a) scenario count growth *weighted by the supervisor's quality verdict* to avoid spam (depends on `pr-98f670e`); (b) coverage delta per scenario with explicit accounting of diminishing returns; (c) bug-recurrence rate with denominator (recurrences per known fix merged, per week). These are aspirational metrics the plan owes — not currently collected — and the lit review treats 'durable' as the defensible claim today, 'compounding' as the future claim contingent on collecting these."

### A7. B1-7 "Durable" vs "compounding" inconsistency — agree, add bridging sentence

**Edit**: add to §3's "durable" passage: "Whether durable tests *compound* — produce more value per cycle than the cycle before — is a separate, stronger question taken up in the Conclusion, where the measurement obligations are listed."

### A8. B1-8 Capstone placement in §1 plot — agree, fix the taxonomy

**Agree.** The reviewer is right that placing the capstone in the "cleanroom" row conflates two categorically different defenses: ProgramBench *denies* internet (cleanroom-at-runtime), the capstone *detects* after the fact (audit-after-run). These are opposite bets, not stricter-vs-looser versions of the same bet.

**Edit**: rebuild the §1 plot. Split the contamination-defense axis into two values: "denial at runtime" (cleanroom, no-internet sandbox) and "detection post-run" (allowlist audit). Place ProgramBench in denial; place the capstone in detection. This makes the plan's distinctive bet visible in the plot, which is what the plot is for.

### A9. B1-9 Missing verifier-guided generation literature — agree, cite

**Agree.** Cobbe et al. 2021 "Training Verifiers to Solve Math Word Problems" and Lightman et al. 2023 "Let's Verify Step by Step" (NeurIPS 2023) are the positive-side literature corresponding to Pan 2024's negative-side critique. The supervisor architecture sits in this sub-genre.

**Edit**: add both to §4. Frame the scenario quality supervisor as a verifier-guided generation pattern, with Pan 2024 as the critique to be defended against. This contextualizes the design within a real research lineage rather than presenting it as a one-off.

### A10. B1-10 Self-Debug granularity mismatch — agree, acknowledge

**Edit**: tighten the §3.2 Self-Debug analogy to: "structurally similar to Self-Debug (Chen et al. 2023) at the prompt-iteration level, but the plan's bug-fix watcher operates at the watcher-tick level — many minutes apart, with a persistent work-log between ticks. The longer feedback loop changes the failure modes: drift, stale context, and intervening discovery-supervisor activity replace Self-Debug's faster-but-tighter pathologies."

## Bucket B — structural and readability (Block 2)

### B1. B2-1 Glossary spine 750-word wall — agree, move to appendix

**Agree.** The current glossary spine in the Introduction asks the reader to internalize 14 terms before reaching the first substantive section, with internal dependencies (e.g., "QA review loop" depends on "regression tests" defined later).

**Edit**: move the glossary to an Appendix titled "Terms used in this review." Replace it in the Introduction with: (a) a 100-word plain-English summary of what the plan does; (b) an inline anchor list naming the terms-used-throughout without definitions, with a pointer to the appendix; (c) inline glosses at first body use of each term, even if redundant with the appendix. Readers who want the vocabulary up-front can read the appendix; readers who don't can rely on inline glosses.

### B2. B2-2 §3 too large — agree, restore APR to own section

**Agree.** Test generation + APR + fakes-as-a-paragraph in one section is a wall. The merge destroyed a useful pause.

**Edit**: restore APR (currently §3.2) to its own §4 (with all subsequent sections renumbered). Add a one-line sub-TOC at the top of the new §3 listing its remaining subsections (test gen, fakes).

### B3. B2-3 Section openings — agree, use reviewer's proposed ones

**Edits**: apply the reviewer's proposed openings for §3.2, §3.3, §5.1, and §6.

### B4. B2-4 Conclusion inventory — agree, cut the 25-name list

**Agree.** Lines 226+ list 25+ paper names as accountability rather than synthesis. The reader has just seen these names.

**Edit**: cut the list. Replace with: "The full citation set, organized by section, is in the References. The walk remains under-budgeted for a full traversal; readers chasing a specific thread should treat the references as a starting set, not a complete one."

### B5. B2-5 Bridges content-free — agree, fold in

**Edit**: cut both standalone bridge paragraphs (between §4/§5 and §5/§6). The bridge content moves into the next section's opening, woven into the new section-opener proposed under B2-3.

### B6. B2-6 §1 plot row labels mixed-kind — agree, rebuild

**Agree, included in the B1-8 edit.** The rebuilt §1 plot uses uniform-kind values on the contamination-defense axis: "no defense → human-filter → time-window → denial-at-runtime → detection-post-run." Brief inline characterizations on each.

### B7. B2-7 Add single watcher-hierarchy diagram — agree

**Edit**: add an ASCII diagram in the Introduction (right after the plain-English summary): external trigger → discovery supervisor → file PR → implementation watcher → QA review loop → scenario quality supervisor → merge gate. Replaces the three slightly-different prose descriptions in Intro/§4/§6.

### B8. B2-8 METR framing-then-caveat — agree, commit or demote

**Edit**: demote METR to a one-clause mention with link: "(see also METR's 2025 informal report on reward-hacking in Recent Frontier Models, an industry source consistent with the formal characterizations above)." No paragraph treatment.

## Bucket C — Block 3 accessibility (per-term glosses)

Accept all proposed glosses wholesale. Specifically:

- **B3-1**: apply all 18 listed gloss additions (pass@k, diff, sandbox/egress, AST/compiler, flaky, mocked-out-too-much, evolutionary test generation, DSL example, AST fingerprints, oracle access, verdict surface, writer-checker-pair / actor-critic naming, venue glossary, AST plagiarism, contamination vocabulary consistency, event-stream, scaffold consistency).
- **B3-2**: rewrite the four glosses that introduced new jargon (hidden unit tests, AST-based program analysis, Reflexion's verbal RL re "weights," edit-distance / AST plagiarism).
- **B3-3**: apply the four proposed section openings (§5.1, §6, §3.2, §3.3).
- **B3-4**: anchor the unanchored benchmark sizes (one-line note: "these benchmarks range from a couple hundred to a couple thousand tasks; HumanEval at 164 tasks is the smallest of the modern set").
- **B3-5**: cut Fowler / Meszaros / Tembo / Haseeb Qureshi from prose; relegate to footnoted references. Add the venue-glossary line.
- **B3-6**: spell out venue abbreviations on the venue-glossary line at the top of References. Cut MT-Bench from References if not used in body.
- **B3-7**: audit "load-bearing" usage and cut by half. Vary "the closest peer in the literature" phrasing.
- **B3-8**: rewrite the §5.2 bullet list as plain prose using the reviewer's proposed text.

## Bucket D — expanded `--resume` problem (the load-bearing residual issue)

This expansion is for the *plan owner*, not the lit review. It belongs in a `pm pr note add` on `pr-98f670e` and possibly in an updated description of that PR. The lit review's edit just acknowledges the design owes future work; the plan's edit is the substance.

### What `--resume` actually does

Claude Code's `--resume <session-id>` reattaches to a saved session. It carries forward:

- The system prompt
- The full conversation history (every user turn, every assistant turn, every tool-use block)
- The tool-use history with results
- Any memory entries persisted by the previous session

It does *not* carry forward:

- In-memory side state of the previous process (Python-level variables, open file handles, anything the previous tick was holding in working memory outside the conversation)
- The model weights themselves (still the same model, no state inside the model)

So a `--resume` session has the same *context-window content* as the original session — it is the same conversation continued, not a new conversation with summaries. The supervisor reading "the scenario's captures via `--resume`" actually means the supervisor session inherits the scenario's full thread.

### Why Pan et al. 2024 still applies

Pan et al. measure "spontaneous reward hacking in iterative self-refinement" — generator and evaluator with shared context produce reward-hacking patterns within 2 to 10 iterations. The key independent variables are:

1. Same model on both sides — yes, our supervisor and scenario both run as Claude
2. Shared context — yes, `--resume` shares the full thread
3. Same-role framing (both told their job is to find/fix issues) — partial; the supervisor's prompt is different from the scenario's, but it sees the scenario's prompt and reasoning
4. Iteration count — Pan et al. find hacking emerging by iteration 2-3 in many configurations

The supervisor's current defense is the amendment cap of 2. Cap of 2 sits exactly in the regime where Pan et al. show measurable hacking. **The cap is necessary but not sufficient as a defense.**

### Design options for stronger context separation

In rough order of strength:

**Option 1 — Fresh session, captures-only input bundle.** Strongest separation. The supervisor session does not `--resume` the scenario's session. Instead it is started fresh with a structured input:
- The scenario's tool-use transcript (exported as a flat log: command, args, output)
- The captured artifacts (output files, screenshots, test results)
- The original PR diff
- The scenario's verdict and assertions, but *not* the scenario's reasoning trace

The supervisor reads the bundle and judges depth-of-evidence without ever seeing the scenario's chain-of-thought. This is closest to what Pan et al. would call "context-separated evaluation."

**Option 2 — Different model.** Use a different model for the supervisor (a smaller verifier model, or a different model family entirely). Eliminates the same-model risk Pan et al. measure but introduces calibration concerns: the supervisor model may apply different judgment standards than the scenario model. Combinable with Option 1.

**Option 3 — Multi-model ensemble.** K=3 fresh-session supervisors (different models or same model with different seeds), majority vote. Expensive but high-confidence for contested verdicts. Reserve for high-stakes decisions (e.g., the verdict that gates merge).

**Option 4 — Adversarial supervisor framing.** Independent of separation. Prompt the supervisor with a high prior on flaws: "find the strongest evidence this scenario took a shortcut." Adversarial framing pushes against the sycophancy-with-prior-turn failure mode even when context is partially shared. Combinable with all the above.

### Recommendation for `pr-98f670e`

Combine Option 1 (fresh session, captures-only input) with Option 4 (adversarial framing). Keep the iteration cap of 2 as a safety, not the primary defense.

For high-stakes verdicts (merge-gating), upgrade to Option 3 (K=3 ensemble of fresh-session adversarial supervisors). The cost is bounded — three Claude sessions per high-stakes verdict, called only on contested cases — and the confidence gain is substantial.

### What the plan's PR should change

`pr-98f670e`'s description should be updated to say:

- The supervisor is launched as a **fresh Claude Code session** (no `--resume`), with an input bundle consisting of: the scenario's tool-use transcript (exported flat), captured artifacts, the original PR diff, and the scenario's emitted verdict.
- The supervisor's prompt is **adversarial**: "find the strongest evidence this scenario took a shortcut. List every check the scenario should have run but didn't. Reach NEEDS_WORK by default; only emit PASS if no shortcut is found."
- The amendment cap of 2 remains as a safety, not as the primary mitigation.
- High-stakes verdicts (specifically, verdicts that gate merge) escalate to a K=3 ensemble of fresh-session adversarial supervisors with majority vote.

These changes shift the supervisor's defense from "shared-context generator-evaluator pair with a small iteration cap" (Pan et al.'s exact failure regime) to "context-separated, adversarial, optionally ensembled" — moving the design out of Pan et al.'s measured-hacking regime entirely.

I will save the design rationale to `pm/docs/adversarial-review/RESUME_DESIGN_NOTE.md` so the plan owner can lift it directly into `pr-98f670e`'s description or notes.

## Bucket E — items not addressed in this response

A few Cycle 3 findings I am not committing to fix in the edit pass because they are convergence-floor nits the reviewer themselves flagged as "phrasing nits":

- "Closest peer" phrasing tic (B3-7 partial)
- "Load-bearing" overuse beyond the audit — to be done in passing during the Block 3 pass but not as a numbered edit
- The OOPSLA / FSE / ISSTA expansion — only OOPSLA actually appears in the review; the others are listed in the venue glossary even though unused. Trim.

## Edits checklist

Before any text changes land in `literature-review.md`:

**Substantive:**
1. Drop ImpossibleBench numbers; replace with "no analogous numbers exist" framing (A1).
2. Tighten §4 `--resume` passage; add Conclusion note acknowledging `pr-98f670e` is the most under-validated mitigation (A2).
3. Drop or pin the 76% GPT-5 figure (A3).
4. Upgrade OpenHands to ICLR 2025, AgentAuditor to NeurIPS 2025, Liars' Bench title fix (A4).
5. Tighten §6 priority claim to "no structured priority field" (A5).
6. Rewrite Conclusion compounding-metrics passage with explicit operational definitions (A6).
7. Add §3 durable-vs-compounding bridge sentence (A7).
8. Rebuild §1 2D plot with split contamination-defense axis (denial vs detection) (A8, B2-6).
9. Add Cobbe 2021 and Lightman 2023 as verifier-guided generation peers in §4 (A9).
10. Tighten §3.2 Self-Debug analogy with granularity caveat (A10).

**Structural:**
11. Move glossary spine to an Appendix; replace Introduction with summary + inline-anchor list (B2-1).
12. Restore APR to its own section (B2-2).
13. Apply the four proposed section openings (B2-3).
14. Cut the Conclusion's 25-name inventory (B2-4).
15. Cut both standalone bridge paragraphs (B2-5).
16. Add ASCII watcher-hierarchy diagram in the Introduction (B2-7).
17. Demote METR to one-clause mention (B2-8).

**Accessibility:**
18. Apply all 18 B3-1 gloss additions.
19. Rewrite the four B3-2 glosses that introduced new jargon.
20. Anchor unanchored benchmark sizes (B3-4).
21. Cut name-drops without context (Fowler, Meszaros, Tembo, Haseeb Qureshi) (B3-5).
22. Add the venue-abbreviation glossary line at the top of References; expand all venue acronyms (B3-6).
23. Audit "load-bearing" usage and cut by half (B3-7).
24. Rewrite §5.2 bullet list as plain prose (B3-8).

**Citation hygiene:**
25. Remove MT-Bench from References if not used in body.

## Closing — declare convergence after the edit pass

The methodology defines convergence as "findings get pedantic; further cycles produce phrasing nits." Cycle 3 itself flagged the convergence threshold. After this 25-item edit pass lands, the loop on `pm/docs/literature-review.md` is **closed**. No Cycle 4.

The two items that *don't* close are:

1. `pr-98f670e`'s design strengthening (the `--resume` problem). That's a plan edit, not a lit-review edit. The standalone design note at `RESUME_DESIGN_NOTE.md` is the input.
2. The compounding-vs-durable measurement obligation. The plan owes operational definitions and a metrics-collection commitment. Until that lands, the lit review will continue to describe "durable" as the defensible claim today and "compounding" as the future claim contingent on collecting the metrics named in A6.

Both items are explicit obligations carried by the plan, with the lit review pointing at them. That is the right resting state for a closed lit-review loop.
