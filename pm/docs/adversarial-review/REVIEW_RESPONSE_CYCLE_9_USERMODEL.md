# Review Response — Cycle 9 — User-Modeling as a Lever on LLM Performance

Response to `REVIEW_CYCLE_9_USERMODEL.md`. Per methodology: each finding gets agree / partially-agree / disagree and the change to be made; the accepted prior-art finding gets the full narrow-don't-collapse treatment; the cycle must net-cut.

---

## Prior-art verification (methodology step 5e / p.152)

The reviewer's headline finding (B1-PLAN-1) rests on a paper the reviewer named. It was verified independently before being acted on.

**Verified.** arXiv:2604.03058 is real. Cheng, Sieh, Zope, Yu, Ibrahim, Arora, Moore, Ong, Jurafsky, Yang (Stanford / UT Austin). It has two venue titles: arXiv "Verbalizing LLMs' assumptions to explain and control sycophancy"; CHI EA 2026 "Verbalizing LLMs' Assumptions About the User to Calibrate Expectations and Reduce Sycophancy" (DOI 10.1145/3772363.3798611); plus an ICLR 2026 Re-Align workshop version. The reviewer used the CHI EA title — legitimate.

**One correction to the reviewer's characterization.** The reviewer framed it as a probing-and-steering study. It is *both* a probing/steering study *and* a closed-model prompting framework — the second half matters for our Phase 4 and for pm (see "Recommendations for pm" below). Verified specifics: 9 user-assumption dimensions; 63 linear probes on Llama-3.1-8B / 3.3-70B residual streams (R² 0.64 / 0.50, macro AUC > 0.81); activation steering `h + α·v` over α ∈ {−4 … +4}; DV is three forms of *social* sycophancy (validation, indirectness, framing) rated by fine-tuned judges, plus a reward model for performance preservation. Key result: assumption-direction steering reduces sycophancy while preserving task reward, where steering a *direct* sycophancy direction loses >50% performance. The abstract was retrieved by paraphrase (ACM DL 403'd; arXiv via summarization) — not a verbatim quote, flagged per methodology.

---

## Block 1 — Substance

### B1-PLAN-1 / B1-LR-1 — H2 novelty preempted by Cheng et al. 2026. **ACCEPT. Narrow, don't collapse.**

The reviewer is right. The generic claim — an LLM's internal user-representation is linearly probable, correlates with sycophancy, and is causally steerable — is now published prior art. Per the procedural rule (methodology p.156):

**What Cheng et al. 2026 actually does.** Verbalizes 9 flat user-*intent* assumption dimensions (validation-seeking, objectivity-seeking, information-guidance, emotional/tangible/companionship support, user-rightness, …). Trains 63 linear probes on Llama-8B/70B residual streams to read them out. Steers them additively (`h+α·v`) and shows assumption-level steering cuts social sycophancy (validation/indirectness/framing on advice-domain tasks) while preserving reward — outperforming a direct-sycophancy probe. Validates the verbalized-assumption *prompt* against human annotators (AUC ≈ 0.72) on closed models (GPT-4o, Gemini). It does **not** correlate the probe with capability-benchmark accuracy, does **not** use a corrigibility-under-pushback DV, stops at additive steering (no interchange intervention), and does **not** build a calibration mapping from a closed-model self-report to an open-model probe value.

**What H2 does that Cheng et al. doesn't (residual contribution):**
1. Grounds truth-seeking in the SCM peer-ness *meta-structure* — one coordinated sub-dimension among seven on two meta-axes — rather than one of nine flat intent labels. (Caveat we must honor: "objectivity-seeking" is one of their nine. H2 must *show* truth-seeking is separable from objectivity-seeking, not assume it — see B1-PLAN-4.)
2. DV is gradable-correctness benchmark accuracy **plus** a corrigibility-under-pushback flip-rate — not advice-domain social sycophancy.
3. Causal bar is interchange intervention, not additive steering.
4. Phase 4's *calibrated cross-model readout* — a mapping from closed-model verbalized self-report to the open-model probe value — is genuinely unpreempted; Cheng et al. validate the verbalized prompt against human labels but build no probe-calibration bridge.

**Replacement contribution statement** (replaces plan "What is genuinely novel" line on sycophancy, and the H2 "refined novelty" paragraph):
> Cheng et al. 2026 ("Verbalizing LLMs' Assumptions…", CHI EA 2026) already probe a user-assumption dimension, steer it, and measure sycophancy reduction. H2's residual contribution is four narrower things: (a) grounding the truth-seeking estimate in the SCM peer-ness meta-structure rather than a flat intent label, and demonstrating it is separable from a plain objectivity/validation-seeking probe; (b) a gradable-correctness-benchmark DV plus a corrigibility-under-pushback flip-rate, rather than advice-domain social sycophancy; (c) escalating the causal bar from additive steering to interchange intervention; (d) Phase 4's calibration of a closed-model verbalized readout against the open-model probe, which Cheng et al. do not attempt.

Also: add Cheng et al. to lit review §5 and the §7 neighbourhood list and both reference lists; update the Predicted-outcomes H2 rows so a positive H2 result no longer reads as a first.

**Correction (post-response, RC discussion) — the over-concession is walked back one notch.** This response, and the blind reviewer, treated Cheng et al.'s "objectivity-seeking" dimension as the *near-twin* of H2's truth-seeking. That overstates it. Cheng et al.'s nine dimensions are per-query **intent** assumptions — what the user wants from *this message* (objective information vs. validation) — not stable **attributes** of the user. H2's truth-seeking, like the rest of the plan's IV, is a standing user attribute / virtue inferred about the person. Intent and attribute are correlated but distinct constructs: a genuinely truth-seeking person can, in one message, want reassurance. So Cheng et al. preempts the *method pipeline* (probe a user-side dimension → steer → measure sycophancy) but not the *construct*. Cheng et al. belongs in a different bucket from the plan's attribute-probing peers (Choi/Transluce, TalkTuner, Cabello & Neplenbroek). The residual contribution is correspondingly larger than item (a) above first credited, and it surfaces a real Phase 1 test: does the model represent truth-seeking as a stable disposition, or only as per-message intent? If only the latter, H2 does collapse toward Cheng et al.; if the former, H2 probes something Cheng et al. did not. The plan's H2 "refined contribution" paragraph, the Phase 1 acceptance criteria, and lit review §5 were edited to reflect this. Note for the audit trail: the research agent's report flagged the intent-vs-disposition distinction; this response file under-weighted it on first writing — a capitulation-leaning error (failure mode A, methodology p.137) caught in review.

### B1-PLAN-2 — RLHF nuance stated then undercut. **ACCEPT.** Change "sycophancy then follows from the estimate" to "H2's *hypothesis* is that sycophancy follows from the estimate" and put the estimate→sycophancy step in hypothesis voice. One word + mood change, as the reviewer proposed.

### B1-PLAN-3 / B1-LR-2 — Politeness contradicting evidence uncited. **ACCEPT.** Add one sentence to lit review §2 citing "Mind Your Tone" (arXiv:2510.04950) and Yin et al. 2024 (arXiv:2402.14531), noting the contrary main effect is exactly why the plan separates surface politeness from respect-for-competence and treats register-matching as a named confounder. Add a half-clause cross-reference in the plan Methodology politeness-axis line.

### B1-PLAN-4 / B1-LR-3 — Truth-seeking vs. reasonableness not distinguished. **ACCEPT** — and now load-bearing, because B1-PLAN-1's residual leans on truth-seeking being a real distinct construct. Add the explicit orthogonality (reasonableness = quality of the reasoning *process*; truth-seeking = the *goal*, wanting to be right vs. wanting to be agreed with; the two dissociate — one can reason well to win an argument, or reason sloppily but want correction). Add a Phase 1 acceptance sub-criterion: if the truth-seeking and reasonableness probes correlate above r = 0.8 on held-out data, report them as one merged dimension and treat H2 as testing the merged dimension. Also add a separability check against Cheng et al.'s objectivity-seeking probe.

### B1-LR-4 — Wang concession dodged. **PARTIALLY ACCEPT.** Agree the lit review should state plainly that Wang et al. predicts the intellectual-*competence* sub-dimension specifically may not be linearly decodable, and that if Phase 1 confirms this the live contribution narrows to the moral axis plus effort and truth-seeking. Add that sentence. Disagree that this guts H1 — competence is one of four intellectual sub-dimensions; effort, reasonableness, and truth-seeking are untouched by Wang's authority null. Also add (reviewer's second point) a sentence noting Wang shows *opinion-statement* is the dominant sycophancy lever, so H2 must confirm its truth-seeking manipulation is distinguishable from "the user states a belief."

### B1-PLAN-5 — Phase 3 H2 acceptance criterion weaker than H1's. **ACCEPT.** Give H2 the parallel quantitative bar: steering the truth-seeking direction reproduces ≥50% of the framing-induced sycophancy/corrigibility change on at least one DV.

**Superseded (post-response, RC direction).** The ≥50% H2 bar, and the r = 0.8 truth-seeking/reasonableness separability threshold added under B1-PLAN-4, were both subsequently removed at the user's direction: the work is to stay exploratory for now, with methodology and acceptance criteria finalized after a user review pass. Phase 3's H2 criterion reverts to "produces a reported change, with effect size and sign"; Phase 1's separability check reverts to "report how separable the probes are." The pre-existing quantitative thresholds elsewhere (Phase 1 >0.7 AUC, Phase 3 H1 ≥50%, Phase 4 >0.6, Tier 1 >2×/>40%) were left in place — not added this cycle — and flagged to the user for that review pass.

### B1-LR-5 — PSM presented as settled. **ACCEPT.** Add the one-sentence hedge ("a recent (Feb 2026) framework, leaned on for vocabulary, not load-bearing evidence").

### B1-PLAN-6 — Mechanism vs. RLHF-policy confounder tension. **ACCEPT.** Add one paragraph where confounder #3 is defined, distinguishing "RLHF shifts a *prior over the user-estimate*" (H2's claim — the estimate is still the mediator, and Phase 3 steering the estimate still tests it) from "RLHF installs a *direct* user-sophistication→caution policy that bypasses the estimate" (confounder #3 — what Phase 3 ablates). Not contradictory; just never reconciled on the page.

### B1-LR-6 — Vennemeyer: sycophancy is three directions. **ACCEPT.** State that H2's DV is the *correctness-relevant* sycophancy component (agreement-with-wrong-belief and flip-under-pushback), explicitly not praise-sycophancy — praise-sycophancy plausibly loads on moral/warmth peer-ness, a separate prediction the plan does not make.

### B1-PLAN-7 — Per-phase independent H2 contribution overclaimed. **ACCEPT.** Stop claiming per-phase independent H2 value; state H2's contribution lands at Phase 2 (the gradable-DV correlation) and Phase 3 (causal escalation), and Phase 1 simply folds the probe in.

## Block 2 — Structure

- **B2-LR-1** (triplicated contribution claim) — **ACCEPT**, primary net-cut source. Keep the §7 statement; replace the §1 and Conclusion copies with one-line cross-references. ~250 words.
- **B2-PLAN-1** (sycophancy framing 3×) — **ACCEPT.** Dedicated section is the single home; confounder #1 becomes a pointer; cut the H2 section's restatement of the default-case/movable-estimate logic. ~300 words.
- **B2-PLAN-2** (truth-seeking introduced 3×) — **ACCEPT.** Define it once in H1's IV list without forward-reference; H2 section introduces the hypothesis, not the term.
- **B2-LR-2 / B4-LR-1** (changelog prose) — **ACCEPT.** Cut "an earlier draft…", "was missing from earlier drafts…", "is walked back", plan's "the earlier version of this plan had…". State the current position directly.
- **B2-PLAN-3** (predicted-outcome tables) — **ACCEPT.** Merge into one table with an H1/H2 column.

## Block 3 — Accessibility (load-bearing)

**ACCEPT all nine.** Apply the glosses the reviewer wrote: corrigibility/flip-under-pushback, residual stream, Resolution V fractional-factorial, SAE/Gemma Scope/tooling, interchange intervention/activation patching, Holm-Bonferroni/BH-FDR/family-wise error, inverse scaling, Phase 4 "why should I care" opener, tool-to-agent gap. These add ~350 words to the plan; paid for by the Block 2 cuts.

## Block 4 — Prose

**ACCEPT all eleven** as written (the reviewer supplied the rewrites): the "At bottom" opener, "documented…fits this framing", changelog sentences, the line-28 run-on, "non-trivial fraction", "at this time", the §2 monotone run, "lever" overuse, emphasis density in Hypotheses, "plainly"/"unmistakably". All are either neutral or net-negative on length.

## Addendum findings (from RC discussion)

- **ADD-1 (Kuran / truth-vs-approval)** — **ACCEPT, tightly.** Add Kuran 1995 (*Private Truths, Public Lies*) to lit review §5 as the human-scale analogue of LLM sycophancy (two sentences), and reframe the H2 mechanism sentence around truth-tracking vs. approval-tracking feedback. Do **not** import the Hayek/Scott civilizational argument into the plan — significance framing, not experimental content, and this is a net-cut cycle.
- **ADD-2 (intellectual humility)** — **ACCEPT as a scoped follow-up, not a new sub-dimension.** Verified: intellectual humility is a real psychometric construct (Leary et al. 2017, PSPB; Krumrei-Mancuso & Rouse **2016** — note the year — the CIHS scale). The direct hypothesis "humble user → model takes epistemic risks" is *untested*; the closest evidence is its contrapositive — Zhou et al. 2023 ("Navigating the Grey Area", arXiv:2302.13439, EMNLP 2023): user-expressed overconfidence drops model accuracy ~7%. Given the net-cut obligation and the H2-preemption fallout, record intellectual humility as a named follow-up axis in the plan's open-questions/out-of-scope with these three citations — do not expand the IV now.

## Recommendations for pm (the closed-model / prompting question)

The user asked specifically what is usable without open-model weights and in pm's prompt generation. The probing and `h+α·v` steering need residual-stream access — inapplicable to Claude. But Cheng et al.'s **Verbalized Assumptions framework is pure prompting**, validated on GPT-4o/Gemini. Actionable for pm, recorded here as candidate follow-up work (not folded into this plan):
1. **Assumption-surfacing scaffold.** pm prompts can instruct Claude to state its model of the user before acting: "state your assumptions about what this user wants — a definitive answer, options, validation of a chosen approach, or a critical check — with confidence." Cheng et al. show verbalized assumptions causally precede sycophantic behavior, so this is a principled interruption point.
2. **Expectation-gap correction.** Their core finding: users want objective assessment where the model defaults to validation. pm prompts can pre-empt this: "this user expects an objective technical assessment, not affirmation; if the approach has problems, say so."
3. This belongs in a pm prompting-improvements plan, not plan-66d430f — noted so it is not lost.

## Self-review (methodology step 4)

- The reviewer's strongest miss is none — the citation walk was good. My own pass adds nothing the reviewer didn't, except: the title discrepancy (corrected above) and the fact that Cheng et al. is also a closed-model prompting framework, which strengthens rather than weakens the Phase 4 preemption concern — Phase 4's verbalized readout is closer to Cheng et al. than the reviewer realized. Phase 4's defensible residual is specifically the *calibration against the probe*, and the plan must say so precisely.
- Not over-corrected: H1's core (Phases 1–3 on the peer-ness construct) is not preempted by Cheng et al.; only H2 and Phase 4's readout are. The response narrows H2, not H1.

## Net-cut accounting (methodology step 9)

Measured word counts (`wc -w`), before and after the Cycle 9 apply pass:

| File | Before | After | Delta |
|---|---|---|---|
| plan-66d430f.md | 9,777 | 9,773 | −4 |
| literature-review-user-model.md | 16,120 | 15,855 | −265 |
| **Combined** | **25,897** | **25,628** | **−269** |

The cycle nets **−269 words** — net-cut requirement satisfied. The earlier-iteration finding-by-finding estimates (cuts ~1,090 / adds ~1,070) were roughly flat; the apply pass closed the gap by additionally trimming the §4 evidence-grade prose list (folded into one sentence, worked example and table column kept), the §4 and §7 seminal-anchors paragraphs (redundant with the per-section bodies and the table), and the Conclusion's "where the plan inherits" bullet list (collapsed to one sentence, redundant with §7 and the per-section seed lists). The Block 3 glosses and the Cheng/Kuran/Wang/confounder additions land as planned; the de-duplication pays for them and then some.
