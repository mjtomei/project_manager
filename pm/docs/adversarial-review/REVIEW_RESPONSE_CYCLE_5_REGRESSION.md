# Review Response — Cycle 5 (regression-loop literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_5_REGRESSION.md`

Cycle 5 surfaced 27 findings (5 substantive, 22 phrasing). Substantive moves below; phrasing rolls into the edit pass.

## Bucket A — substantive findings (5)

### A1. B3.2 — Inspect attribution is wrong

**Agree, fix immediately.** The lit review currently attributes Inspect to "Anthropic / AISI." Inspect is the **UK AISI's** open-source evaluation framework. The Anthropic ↔ AISI partnership is separate (Anthropic uses Inspect; doesn't own it). This is a factual error.

**Edit**: replace every "Anthropic / AISI" or "AISI / Anthropic" attribution for Inspect with "UK AISI's open-source evaluation framework, used by Anthropic for some alignment audits." Verify by checking aisi.gov.uk before applying.

### A2. B1.1 — Missed SWT-Bench-cluster prior art

**Agree.** The forward-walk from SWT-Bench surfaced Issue2Test, SWE-Tester, e-Otter++, TestExplora — none in any prior cycle. These bear on §3.1 (test generation) and the plan's `pr-2680fbf` (planner authors a new regression when none fits).

**Edit**: verify each citation via WebFetch (apply the methodology's verification step). For each that verifies cleanly, add to §3.1 as the recent prior-art wave on LLM-driven test generation. Narrow `pr-2680fbf`'s novelty against whichever of these does closest peer work.

**Replacement contribution statement** (per the methodology principle, to be refined after verification):

> "The plan's `pr-2680fbf` (planner authors a new regression when none fits) extends [closest peer's methodology] with [specific residual contributions]. The exact replacement depends on which of Issue2Test / SWE-Tester / e-Otter++ / TestExplora does work closest to `pr-2680fbf`'s setup; the edit agent will verify and choose the most-load-bearing peer to narrow against."

### A3. B1.5 — "Formal end of SWE-Bench Verified" overstated

**Agree.** The current §1 text reads as if OpenAI formally retired SWE-Bench Verified across the board. The actual move was an audit of the hardest tasks finding ≥59.4% flawed and a recommendation to migrate to SWE-Bench Pro for the affected subset. The framing should match the verified scope.

**Edit**: rewrite the §1 passage to: "OpenAI audited the 138 hardest remaining tasks in SWE-Bench Verified and found ≥59.4% materially flawed (49 over-narrow + 26 under-specified); they recommended SWE-Bench Pro as the replacement going forward." Drop "formal end" / "retired" / "abandoned" framings.

### A4. B1.3 — §6.2 "five fronts" contradicts §6.3 precedent list

**Agree.** §6.2 says the capstone tackles "five fronts." §6.3's precedent list shows three of those fronts are addressed by NIST/AISI/Meerkat/AuditBench. The "five fronts as novel" framing is inconsistent with what §6.3 acknowledges.

**Edit**: rewrite §6.2's framing. The capstone tackles ≤3 fronts that are genuinely residual after the §6.3 precedents; list them specifically rather than claim "five." This is a follow-on to the Cycle 4 document-wide novelty restructuring that didn't fully ripple to §6.2.

### A5. B1.4 — ProgramBench evidence-base caveat not propagated to contribution claims

**Agree.** §1 acknowledges ProgramBench's evidence-base is thinner than SWE-Bench's (smaller scale, fewer follow-ups, more recent). Subsequent passages still treat ProgramBench as if it were a settled benchmark precedent. The caveat should propagate to any claim that references ProgramBench as an established target.

**Edit**: audit every ProgramBench mention; where the claim depends on ProgramBench being a settled benchmark, add the caveat inline ("ProgramBench, though its evidence base is thinner than SWE-Bench's..." or similar).

## Bucket B — phrasing/structural improvements (22 nits)

Roll up into the edit pass per the Cycle 5 review's specific text. Notable items:
- Gloss `verifier-guided generation`, `sycophancy`, `sandbagging`
- Anchor unanchored percentages (32.8%, 54%, 59.4%) with comparison anchors
- Numbered-list §6.2's five fronts (now three after A4)
- Vary §6.3's seven citation-led paragraph openings (currently each starts with the citation name; vary)

## Edits checklist

1. Fix Inspect attribution everywhere (UK AISI, not Anthropic/AISI). Verify on aisi.gov.uk.
2. Verify Issue2Test / SWE-Tester / e-Otter++ / TestExplora via WebFetch; add the ones that verify cleanly to §3.1; narrow `pr-2680fbf`'s novelty against the closest peer.
3. Rewrite §1 SWE-Bench Verified passage to match OpenAI's verified scope (138 hardest tasks audited, ≥59.4% flawed, SWE-Bench Pro recommended). Drop "formal end" / "retired" framings.
4. Rewrite §6.2's "five fronts" → ≤3 specific residual contributions consistent with §6.3's precedent list.
5. Propagate ProgramBench evidence-base caveat to every claim that relies on ProgramBench being a settled benchmark.
6. Apply the 22 phrasing nits per Cycle 5 review specifics.

## Plan-owner items

If the SWT-Bench-cluster verification (Issue2Test etc.) surfaces a paper that does what `pr-2680fbf` proposes (planner-authors-regression-when-none-fits), the plan's `pr-2680fbf` description should narrow accordingly. Surface to the edit agent — they verify and report which peer is closest.

## Convergence note

The Cycle 5 walk found 5 net-new substantive items (factual error + missed-wave + 3 framing inconsistencies). The pattern suggests the substantive yield is shrinking compared to Cycle 4's 10 substantive findings. The §6.3 cluster's "five seeds confirmed no-adds" is a positive convergence signal for that section. After this pass, the next cycle should test whether the §1 / §3.1 / §6.2 fixes hold against fresh eyes — if mostly phrasing nits return, the loop closes.
