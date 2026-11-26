# Review Cycle 5 — Literature Review: User-Modeling as a Lever on LLM Performance

Reviewer: fresh blind Cycle 5 pass. Did not read prior cycle artifacts before forming findings; cross-reference appendix appears at end.

Artifact: `pm/docs/literature-review-user-model.md`, ~9,871 words, 354 lines.

Convergence prediction from the prompt: Cycle 4 expected Cycle 5 to yield only phrasing nits. I tested that prediction honestly. The result is mixed — most of what I found is phrasing/pedantry, but I found one real substantive issue (finding S1 below) and one moderate framing issue (S2). The rest are nits.

---

## Block 1 — Substance

### S1. [SUBSTANTIVE] The "empirically agnostic between SCM and Goodwin" framing in §1 is technically true but materially misleading.

Lines 48 and 230 frame the SCM-vs-Goodwin choice as one Phase 1's factor analysis will resolve, and say "both frameworks predict that morality-related and competence-related judgments load on distinct factors." That sentence is literally correct but smuggles past a real issue:

- SCM predicts **two factors**: warmth (which includes morality as a subcomponent) and competence.
- Goodwin et al. 2014 explicitly argued that warmth decomposes into **morality** and **sociability** — i.e., Goodwin predicts a **three-factor structure**: morality, sociability, competence.

If Phase 1's factor analysis recovers three factors (one of which is a sociability/affiliative-warmth factor distinct from honesty/good-faith), the plan's two-axis structure (intellectual = competence sub-dims; moral = honesty + good-faith + respect) is *not* validated — it is partially falsified, because "respect" and "good-faith" may load differently than "honesty." The lit review does not say what the plan does in that case. The §7 predicted-outcomes table has no row for "factor analysis returns three factors with sociability separable from morality." This is a real gap.

The response-file claim that the framing is "empirically defensible because both frameworks predict morality and competence load on distinct factors" is a sleight of hand — it states the weakest shared prediction (distinctness of morality from competence) and uses that to claim agnosticism, but the plan's two-axis IV structure makes a stronger commitment (that all of honesty + good-faith + respect load together as one moral factor distinct from a competence factor), and the stronger commitment is *not* shared between SCM and Goodwin.

**Fix**: add a row to the §7 predicted-outcomes table for "factor analysis returns three or more factors (Goodwin-consistent: morality, sociability, competence separable)." Either the plan reorganizes its IV to a three-axis structure at that point, or it commits to two-axis and notes that finding ranks higher than partial falsification. Also revise the §1 "empirically agnostic" sentence: replace with "if Phase 1's factor analysis returns two factors, the result is consistent with both SCM and Goodwin's competence-versus-everything-else split; if it returns three, Goodwin's three-factor structure is supported and the plan's two-axis IV must be revised."

### S2. [MODERATE] Phase 1's "falsifiability lead" still hedges on what is being ruled out.

Line 230 reads: "Phase 1's strongest claim isn't that it will find a peer-ness representation — it's that the construct-validity test could *rule out* the meta-axis structure even if individual peer-ness sub-dimensions exist."

This is structurally good (lead with the falsification claim) but the prose then immediately backs away: "What Phase 1 contributes if it doesn't falsify: extends Choi's user-attribute decoding methodology…" The reader is told what Phase 1 might rule out, but the *consequence* — what the plan does next, whether Phase 2/3 still run, whether the construct gets revised mid-flight — is not stated. Without that, "falsifiability" is decorative.

**Fix**: append one sentence: "If Phase 1's factor analysis rejects the two-axis structure, Phases 2–4 are suspended and the plan is rewritten around whatever factor structure emerged; the construct revision itself becomes the Phase 1 deliverable."

### S3. [NIT] Choi/Transluce evidence-grade upgrade in §4 is accurate but the table cell wording is awkward.

I verified via transluce.org/user-modeling: the paper does use (a) decoder/probe read-out, (b) gradient-based steering optimization through the decoder, and (c) circuit-discovery-based neuron interventions. The Cycle 4 edit ("decoding + gradient-based causal interventions + circuit-based causal interventions") is **substantively correct**. The phrasing in the table cell is verbose. Suggest: "decoding + gradient steering + circuit interventions" — same content, tighter.

### S4. [NIT] §1 vs §7 SCM treatment is borderline-redundant.

§1 introduces SCM and the Goodwin alternative (lines 46–48). §7 ("Multi-axis contrast-pair design" subsection and the predicted-outcomes context) re-invokes SCM and the meta-axis structure, and the conclusion-section anchor list repeats Fiske/Cuddy. This is not pure duplication — §7 uses SCM to anchor the falsification test, which is a different load-bearing use than §1's "where the IV structure comes from." But the *prose* in §7 around "SCM-grounded peer-ness structure" reads as recapping §1 rather than building on it. Cut "regardless of whether the individual sub-dimensions exist" from line 230 (already implied) and let the falsification claim stand alone. Minor improvement.

### S5. [NIT] §4 paper-summary table earns its space but row order is inconsistent with prose order.

The table at lines 113–126 lists papers roughly chronologically (Subramani 2022 → Choi 2025). The prose that follows discusses them in a different order (Zou 2023 first because it's the "seed reference"). A non-expert reader scanning the table then trying to find Zou in the prose hits a mismatch. Either reorder the table to match prose-discussion order, or add a "discussed in order: Zou → Subramani → Turner → ..." sentence between table and prose.

---

## Block 2 — Structure and Readability

### R1. [NIT] Resolution V gloss is now nested-parenthetical-heavy.

Line 212: "Resolution V is the design strength at which all main effects and all two-factor interactions can be estimated separately from each other (Resolution III, by contrast, aliases two-factor interactions with main effects — *aliases* meaning: pairs of effects the design can't tell apart; at Resolution V, only effects of order three or higher are aliased, which is acceptable for two-factor analysis — fatal at Resolution III here, because the whole point is to dissociate the axes)."

That is one sentence with a parenthetical that contains an em-dashed sub-clause that contains another em-dashed sub-clause. The non-developer reader is two embeddings deep before reaching the actual point. Split:

> Resolution V is the design strength at which all main effects and all two-factor interactions can be estimated separately. *Aliasing* — when the design can't tell two effects apart — only happens at order three or higher, which is acceptable for two-factor analysis. (Resolution III, the weaker alternative, aliases two-factor interactions with main effects, which would be fatal here because the whole point is to dissociate the axes.)

Three sentences, no nested parentheticals. Communicates the same content.

### R2. [NIT] Predicted-outcomes table row count is at the upper edge of scannable.

Six rows plus the "outcome shapes the table does not promote" paragraph below. For a non-developer reader, six is borderline; the new "model-family heterogeneity" row reads as a possible-but-not-load-bearing outcome compared to the other rows, which are all yes/no/which-axis-wins shapes. The heterogeneity row's interpretation column adds real information ("training-data-dependent inheritance") but it sits awkwardly because its Phase 3 cell is "(per family)" — a placeholder rather than a parallel-shaped outcome. Consider either (a) demoting the heterogeneity row to the "shapes the table does not promote" paragraph below, or (b) rewriting its Phase 3 cell to match the parallel structure of the other rows (e.g., "Causation present in some families, absent in others — confirmed by per-family interchange intervention"). My recommendation: (b), keep the row.

### R3. [NIT] Section openings — most pass the "why this section" check post-Cycle-4. §1 still doesn't.

§4, §5, §6, §7 all open with "*Why this section.*" framings — works well. §1 opens "Two threads of prior work converge on the plan's hypothesis." That's a research-paper opening, not a "why should I care" opening. A non-developer reading §1 wants to know what they get from reading it. Suggest: add one sentence as the §1 opener: "*Why this section.* The plan's central guess — that LLMs work better when they think the user is a peer — has both empirical and theoretical company in prior literature. This section names the two lines and how the plan inherits from them."

§2, §3, §8 also lack the explicit "why this section" hook. Less critical because their first paragraphs are concrete, but consistency would help.

### R4. [NIT] Glossary in §1 is good but "RLHF" and "Alignment" appear before they're load-bearing.

The §1 glossary glosses RLHF and Alignment. RLHF doesn't appear load-bearingly until §5 (sycophancy). Alignment never reappears load-bearingly. Move these glosses to first-load-bearing-use or drop alignment.

---

## Block 3 — Non-Expert Accessibility (load-bearing)

### B1. [NIT] "Peer-ness" gloss survives Cycle 5 scrutiny — mostly.

Line 9 glosses peer-ness as "how much the model perceives the user as an equal partner, in the same way a colleague perceives another colleague as a fellow professional rather than as a client or a beginner." This works. The gloss does not introduce new jargon a non-developer would not have. The colleague-client-beginner spectrum is concrete and accessible. Pass.

One nit: "meta-dimensions" in the same sentence is jargon. Non-developers know "dimensions"; "meta-dimensions" sounds like a fancier version without adding meaning. Replace "two meta-dimensions" with "two top-level dimensions" or "two umbrella dimensions." Throughout the document, "meta-axis/meta-dimension" appears ~25 times — replacing globally would be cleaner.

### B2. [NIT] "Aliases" gloss inside the Resolution V passage is mid-sentence; reader has to re-orient.

See R1 fix.

### B3. [NIT] "Fractional factorial" still has only one definition (line 202), and Resolution V references it many lines later. By the time the reader reaches Resolution V, they've forgotten. Minor — the definition is two paragraphs up — but consider adding a parenthetical reminder at first Resolution V use: "(see fractional-factorial gloss above)".

### B4. [NIT] "Alpaca" gloss inside the ITI paragraph is parenthetical and may break flow.

Line 142: "Truthfulness on TruthfulQA jumps from 32.5% to 65.1% on Alpaca (an instruction-following dataset built from GPT-3.5 outputs in 2023, widely used as a fine-tuning baseline) — roughly doubling correctness."

The gloss is correct but the reader has to track three things in one sentence (numbers, dataset name, scale-anchor). Suggest splitting: "Truthfulness on TruthfulQA jumps from 32.5% to 65.1% — roughly doubling correctness. (The model tested was Alpaca, a 2023 instruction-following dataset built from GPT-3.5 outputs and widely used as a fine-tuning baseline.)"

### B5. [NIT] "72 billion parameters — roughly the size of Llama-3-70B, mid-sized by 2026 standards; Claude Opus and GPT-5 are believed to be several times larger" — good scale anchor, but the "believed to be" hedges. The reader doesn't need that hedge. Replace with "Claude Opus and GPT-5 are larger" — same useful directional anchor, no insider-only hedging.

### B6. [NIT] §8's CoT gloss appears after MMLU/GSM8K/HumanEval prose, but CoT is referenced in §3 (line 88) where Wei et al. is cited without saying what chain-of-thought is. Either (a) move the CoT gloss earlier to §3 first-use, or (b) add a one-clause inline gloss at line 88: "Wei et al. (NeurIPS 2022) — chain-of-thought (asking the model to think step by step before answering)."

### B7. [PASS, NOTING] Sycophancy reframing is consistent across §1 glossary, §5, §7 predicted-outcomes table, and Phase 3 description. I read all four passages carefully looking for residual treatments of sycophancy as an input-stage confound and did not find any. Cycle 2–3 cleanup held. Convergence on this point.

### B8. [PASS] "Calibration" gloss in §6 line 176 is clear and survives scrutiny.

### B9. [NIT] "Linear Foundation" parenthetical in §3 is name-drop-y. "(now stewarded by the Agentic AI Foundation under the Linux Foundation — the Linux Foundation is a non-profit that hosts shared open-source standards, giving AGENTS.md a neutral institutional home)" — this is two glosses (Agentic AI Foundation, Linux Foundation) plus a value-judgment ("neutral institutional home") in one parenthetical. Most non-developers know Linux Foundation by reputation; many won't know Agentic AI Foundation. Trim to: "(now stewarded by the Linux Foundation, the non-profit that hosts shared open-source standards)" — drop Agentic AI Foundation entirely or treat it as a subsidiary detail.

### B10. [NIT] §1 "*Warmth-terminology note*" parenthetical is necessary disambiguation but is heavy reading. Consider splitting it into its own glossary bullet rather than burying it in the SCM paragraph.

---

## Convergence assessment

**Cycle 4's prediction was that Cycle 5 would produce only phrasing nits.** My honest assessment: the prediction was *mostly right but not entirely right*.

- One real substantive finding (S1: the SCM-vs-Goodwin agnosticism framing papers over a real gap — what does the plan do if Phase 1 returns three factors?). This is not a phrasing nit. It is a missing predicted-outcome row and a glossed-over framework difference.
- One moderate framing issue (S2: falsifiability lead doesn't say what happens if Phase 1 falsifies).
- Everything else (S3–S5, R1–R4, B1–B10) is phrasing-level, table-formatting-level, or section-opener-level. These are pedantic by any reasonable standard.

**Recommendation: one more cycle, then close.** Specifically:

- Cycle 5 response should address S1 (add the three-factor row to the predicted-outcomes table; revise the "empirically agnostic" sentence) and S2 (one-sentence consequence statement on the falsifiability lead).
- The remaining nits can be batched into a final copy-edit pass and do not need adversarial review.
- **Do not run a full Cycle 6** unless the S1/S2 fixes introduce new substance worth attacking. If they're applied cleanly, the loop has converged. The next reviewer would be hunting for word-substitutions, which is below the noise floor of this methodology.

In short: the loop has *not quite* converged at Cycle 5 — one real bite remains — but it is one substantive finding away from convergence. Close the loop after a targeted Cycle 5 response, skip Cycle 6, or run Cycle 6 only as a verification pass with a sharply narrowed scope (just check S1's fix).

---

## What prior cycles missed (cross-reference appendix, written after independent review)

After drafting the above, I read REVIEW_CYCLE_1–4_USERMODEL.md and the response files. Observations:

- **Cycle 4 explicitly raised the Goodwin-vs-SCM question** and the response file added the line 48 "empirically agnostic between SCM and Goodwin" sentence. My S1 finding is the deeper version of what Cycle 4 surfaced: Cycle 4 noted Goodwin should be acknowledged; my Cycle 5 pass shows the acknowledgment papers over the real problem (a Goodwin-consistent factor structure would falsify, not merely revise, the plan's two-axis IV). **This is a finding prior cycles did not fully land.** Cycle 4 got the citation in; Cycle 5 shows the framing the citation enables is still misleading.

- **The §1 vs §7 SCM redundancy** was flagged by the Cycle 3 edit-application notes as a likely Cycle 4 catch and Cycle 4 did not address it. My S4 confirms it remains, though I downgrade it to a nit — there's a defensible reason §7 re-anchors on SCM (different load-bearing use). Prior cycles may have been right not to prioritize.

- **The predicted-outcomes-table row count** was not flagged by prior cycles; my R2 is new. Borderline-pedantic.

- **The "falsifiability lead doesn't state consequence" issue (S2)** is genuinely new. Cycle 4 flagged the "either way" hinge as hedgy; the Cycle 4 response restructured the lead to put falsifiability first. But the restructured version still doesn't say what happens *if* falsification occurs. Cycle 4's reviewer caught the hedge; Cycle 5's pass shows the fix re-introduced a different version of the same hedge.

- **Section-opener consistency (R3)** was not raised by prior cycles. The "*Why this section.*" pattern was introduced in earlier cycles for §4–§7; §1, §2, §3, §8 do not follow it. This is a low-priority consistency nit.

- **Choi/Transluce verification**: I independently verified the gradient + circuit claim against transluce.org. Confirmed. Prior cycles also raised this; my pass confirms the Cycle 4 edit was correct on the merits.

- **Resolution V gloss density (R1)** matches Cycle 4's observation that the prose became nested-parenthetical-heavy. Cycle 4 flagged it; the source was not edited; my finding restates Cycle 4's at one cycle's remove. Probably means the edit was deferred as not worth the disruption.

- **What no prior cycle has done** is independently fetch the Goodwin paper to test the "agnostic" claim. I attempted via PsycNet/ResearchGate/Semantic Scholar but could not get the abstract (paywall + scraping blocks). My S1 finding rests on general knowledge of the Goodwin paper's argument (morality as a separable construct distinct from sociability/affiliative warmth), not direct verification of the abstract for this review. **Flag**: if S1's fix relies on getting Goodwin's factor-structure claim exactly right, the response cycle should obtain the actual paper (institutional library access, not WebFetch) before drafting the predicted-outcome row.
