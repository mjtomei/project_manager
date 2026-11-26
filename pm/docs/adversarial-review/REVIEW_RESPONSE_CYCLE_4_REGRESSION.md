# Review Response — Cycle 4 (regression-loop literature review)

Date: 2026-05-15
Responding to: `REVIEW_CYCLE_4_REGRESSION.md`

Cycle 4 surfaced 15 findings (10 substantive, 5 phrasing). The big pattern: per-citation framing of the walk additions was honest, but the **document-wide novelty framing** wasn't updated to match. The new METHODOLOGY.md principle ("narrow the contribution; don't collapse it") was applied at the citation level but not at the summary level. This response addresses the integration work and the cross-cluster miss.

## Bucket A — document-wide novelty restructuring (3 findings)

### A1. §1 contamination-defense matrix understates the precedent set

**Agree.** The matrix's "detection post-run" row still positions the capstone alone — but AISI Inspect Scout, NIST CAISI, and Meerkat now also live there. The walk-addition edits put each citation inline in the right place; the matrix itself wasn't updated.

**Edit**: update the matrix. The "detection post-run" row now contains multiple peers; the capstone's distinctness is not "alone in the quadrant" but rather "applies post-run audit to a different threat (runtime-internet lookup) than the precedents (alignment auditing for hidden behaviors, transcript-review for cheating)." Make this distinction explicit in the matrix caption.

### A2. §6 opener doesn't acknowledge the new precedent set

**Agree.** The §6 opener was written when NIST was the lone precedent. Now NIST + AISI + Meerkat + AuditBench co-occupy that space. The opener should acknowledge this.

**Edit**: rewrite the §6 opener. Drop "the literature is thin" framing wherever it survives. The new opener positions NIST CAISI + AISI Inspect Scout as the *two* direct precedents (one US, one UK; both transcript-review pipelines), with AuditBench and Meerkat as adjacent.

### A3. Conclusion novelty inventory still reads as if the capstone is unique in its design space

**Agree.** The Conclusion lists the plan's contributions including the runtime-internet integrity audit as a load-bearing novelty. Post-walk, the residual contribution narrows: the capstone applies post-run audit *to a different threat than the precedents address*. The precedents handle alignment-auditing of hidden behaviors (AuditBench) and transcript-review for known cheating modes (NIST CAISI, AISI Inspect Scout, Meerkat). The capstone applies the same architectural pattern to runtime-internet lookup, which is a different threat.

**Replacement contribution statement** (per the new methodology principle):

> "The capstone's contribution is no longer 'a novel post-run audit architecture' — that architecture was established in 2024-2025 by NIST CAISI and AISI Inspect Scout. The contribution is *applying that architecture to a different threat*: runtime-internet lookup-of-the-answer during autonomous agent runs, distinct from the alignment-auditing setups (AuditBench) and transcript-review setups (NIST, AISI) the precedents address. The residual novelty is the threat-model match, the allowlist mechanism specific to internet-permission contexts, and the integration of the audit into the autonomous loop's verdict pathway."

**Edit**: rewrite the Conclusion's novelty inventory with this framing. The contribution narrows but does not collapse.

## Bucket B — cross-cluster miss (1 finding)

### B1. Persona Vectors should be cited in §5

**Agree.** The walker partitioned interpretability work out of scope and missed the sycophancy connection. Persona Vectors (Chen, Arditi, Sleight, Evans, Lindsey 2025, arXiv:2507.21509) is already cited in the sibling user-model lit review and is verified content: probes the model's *own* persona traits including sycophancy as a direction. This bears on §5's discussion of sycophancy as a behavioral failure mode in headless mode — the supervisor's job is partly to detect runs that go sycophantic, and Persona Vectors gives the methodological precedent for what a "sycophancy direction" looks like.

**Edit**: add Persona Vectors to §5 alongside Pan 2024 + Sharma + Perez. Frame as: "Persona Vectors (Chen, Arditi, Sleight, Evans, Lindsey 2025) provides the precedent for treating sycophancy as a model-side direction in activation space — the kind of artifact a future scenario quality supervisor could probe for directly in evaluating autonomous-loop runs."

## Bucket C — Block 3 accessibility (4 glosses)

Four glosses needed for terms introduced in the walk additions:

- **"tool-to-agent gap"** (AuditBench): gloss as "the gap between what an LLM-as-judge tool catches when asked one-shot vs. what an LLM agent catches when given the same evidence and time to investigate"
- **"realism win rate"** (Anthropic auditing work): gloss as "the rate at which auditors achieve a verdict that holds up under fuller human review"
- **"investigator agent"** (auditing literature): gloss as "an LLM acting as an auditor; given access to a target model's transcript / outputs, asked to identify behaviors of interest"
- **"eval-awareness"** (Inspect Scout): gloss as "the model's recognition that it is being evaluated rather than serving a real user — relevant because models sometimes behave differently when they detect evaluation"

## Bucket D — phrasing (5 findings)

Roll up into the edit pass per the Cycle 4 review's specific text.

## Edits checklist

1. Update §1 contamination-defense matrix: the "detection post-run" row contains multiple peers; capstone's distinctness is threat-model-match, not quadrant-alone-ness.
2. Rewrite §6 opener: NIST CAISI + AISI Inspect Scout as two direct precedents; AuditBench + Meerkat as adjacent.
3. Rewrite Conclusion novelty inventory with the narrowed residual contribution statement.
4. Add Persona Vectors to §5 + References (alongside Pan 2024 + Sharma + Perez).
5. Add the four §3 accessibility glosses (tool-to-agent gap, realism win rate, investigator agent, eval-awareness).
6. Apply the 5 phrasing findings per the Cycle 4 review's specific text.

## Plan-owner items

No plan-edit items from this cycle. The lit review's novelty narrowing affects how `pr-e2b7fdf`'s "capstone novelty" is *described* in the lit review, but the PR's actual design is unchanged.

## Convergence note

This is the document-wide-integration cleanup the lit review's prior cycles missed: the walker's per-citation additions were honest but didn't ripple to the summary frames. After this Cycle 5 edit pass, the lit review's high-level novelty claims will be consistent with its per-citation acknowledgments. Cycle 6 should produce only phrasing nits if convergence holds.

Apply the new "narrow the contribution; don't collapse it" principle: at both the citation level (already done) and the document-wide summary level (this pass).
