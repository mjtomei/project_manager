# Review Cycle 4 — Literature Review on Autonomous Regression and Bug-Fix Loop

**Artifact:** `pm/docs/literature-review.md` (~9,877 words, post-citation-graph-walk).
**Date:** 2026-05-15.
**Reviewer:** fresh Claude session, blind to prior cycles until the final cross-reference appendix.
**Purpose:** test whether the ~9 new citations (~1,100 new words) the citation-graph walk added have slotted in cleanly or opened new substantive issues. Prior loop converged at Cycle 3; this is the post-walk pressure test.

---

## Block 1 — Substance

### B1-1. [SUBSTANTIVE] The capstone's novelty story has eroded but the prose still trades on it

This is the single biggest post-walk issue. Before the walk, §6.3 framed NIST CAISI as *the* one direct precedent — "transcript-walk auditing with internet access at runtime, used to detect benchmark cheating." That made `pr-e2b7fdf`'s capstone an integration job over one published peer, which left the design carrying meaningful "this is a new shape" weight.

After the walk, §6.3 now names: NIST CAISI, AISI Inspect Scout (open-source tool, with seven-step published pipeline, shipped scanners for refusal/eval-awareness/tool-errors), AISI's 6,390-transcript CTF case study (published failure-mode quantification on a similar agent-on-task shape), Meerkat (across-traces cluster audit with reported 4x reward-hacking finding on CyBench), AuditBench (alignment-auditing investigator benchmark documenting tool-to-agent gap), the Anthropic overt-saboteur paper (audit+human-review as published rationale), Petri 2.0 (auditor-realism mitigations), coding-audit-realism (realism-win-rate metric), and the 2025 Anthropic auditing-agents note (Investigator/Evaluator/Red-Teamer decomposition). That is *nine* peer or near-peer published methodologies for transcript-walk auditing, several with shipped open-source code and named pipelines. The capstone's `pm_core/bench/audit.py` is now one more entry in an actively-shipping field.

The Conclusion (lines 247-248) and §6.3 closing paragraph (line 207) attempt to acknowledge this — "The audit in `pr-e2b7fdf` is largely an integration job on top of NIST's and AISI's transcript-walk shape." Good. But the lead paragraph of §6 (line 165) still says the capstone is "the most consequential bet" the plan is making and §1's bottom of the matrix (lines 76-80) still positions "the plan's capstone" alone at the "detection post-run" cell, as if it owns that quadrant. After the walk, AISI Inspect Scout *also* lives in that cell. The matrix is now wrong in the same way the §6 lead is now overstated.

**Specific rewrites required:**

- §1's matrix (lines 76-80): replace "the plan's capstone" with "AISI Inspect Scout / NIST CAISI / Meerkat / the plan's capstone." The capstone is not alone in the cell anymore.
- §6 opener (line 165): replace "the area where the plan is making the most consequential bet" with "the area where the plan most depends on still-actively-shipping prior work." The bet framing is no longer defensible.
- Conclusion line 247: "If the plan succeeds, the capstone is the most distinctive thing it will have shown" — soften to "If the plan succeeds, the capstone is the most ambitious integration it will have shipped." Distinctive overstates against AISI Inspect Scout, which is already published with the same pipeline shape.

This is a substantive finding, not phrasing: the walk genuinely shifted the novelty story and the prose's high-level summary frames haven't all been updated. Three locations name-check the new prior art; three other locations continue as if the walk hadn't happened.

### B1-2. [SUBSTANTIVE] AuditBench framing — honest about the literal non-transfer, but the structural-concern transfer is itself overstated

Line 155 says AuditBench "does not transfer literally" (alignment auditing for hidden behaviors vs. QA-scenario auditing) and that "the structural concern (a checker reading evidence and aggregating it into a verdict can fail at the aggregation step even when the evidence is good) is shared." This is the kind of careful narrowing that reads well — but on close read, the *direction* of the AuditBench gap is opposite to what the scenario-quality supervisor needs.

AuditBench's tool-to-agent gap is: investigators were *given good tools that surface accurate evidence*, and still failed at the verdict step. The scenario-quality supervisor in `pr-98f670e` is on the other side of this — the supervisor *is* the agent that aggregates. The transferable lesson is therefore "the supervisor is the weak link," which §5 does say. But the lit review elides which way the analogy actually runs: AuditBench's investigator-agents had *high-quality evidence at hand* and still missed. The scenario-quality supervisor reads transcripts and captures of variable quality. If anything, the AuditBench result implies the supervisor's task is *harder* than AuditBench's investigators', not just analogous. The current prose flattens this into "shared structural concern" without naming the asymmetry.

**Fix:** add one sentence after the existing AuditBench paragraph noting "the analogy runs in the harder direction for the plan: AuditBench's investigators received curated tool outputs and still failed at aggregation; the scenario-quality supervisor reads transcripts whose quality is itself a variable, so the verdict step is exposed on both axes." This is the honest reading of the result, and it's a stronger argument for the RESUME_DESIGN_NOTE redesign.

### B1-3. [SUBSTANTIVE] AISI Inspect Scout's "operational sibling to NIST CAISI" framing is honest, but the lit review hasn't restructured §6.3 to reflect that

§6.3 opens (line 191) "The two closest direct precedents are NIST's CAISI cheating-evaluation work and AISI's Inspect Scout transcript-analysis pipeline." Good. But then NIST CAISI gets two long sentences and AISI Inspect Scout gets a single long sentence about the seven-step pipeline (line 193), and AISI's CTF case study gets a separate sentence about its 6,390-transcript scope and three failure-mode categories. Treatment is asymmetric: NIST is described in the abstract ("a system that runs an LLM reviewer over an evaluation transcript and scores it for cheating signals"), AISI is described with a concrete count (6,390 samples, 71 CTF tasks, 10-30% refusal rate). The reader who reaches §6.3 cold will read the AISI material as the better-substantiated of the two precedents because it is.

But the §6.3 closing paragraph (line 197) reverts to listing them in alphabetical order ("NIST CAISI, Inspect Scout, and Meerkat"). And the Conclusion (line 247) lists them in order of appearance ("NIST CAISI and AISI's Inspect Scout pipeline"). NIST keeps getting top billing despite the lit review's own evidence that AISI's is the more concrete published peer.

This isn't dishonest — it's just inconsistent. The cleaner move is to lead §6.3 with AISI Inspect Scout (concrete published methodology with shipped tool and case study), then NIST CAISI as the methodology predecessor that motivated it, then Meerkat as the across-traces sibling. The current ordering preserves the pre-walk hierarchy.

**Fix:** invert §6.3's lead paragraph order — AISI Inspect Scout first, NIST CAISI second, Meerkat third. The current order reads as if the walk's additions were appended rather than restructured around.

### B1-4. [SUBSTANTIVE] Persona Vectors (Chen, Arditi, Sleight, Evans, Lindsey 2025, arXiv:2507.21509) is a citation-graph-walk miss in §5

The walk's seed list explicitly named Pan 2024 (Spontaneous Reward Hacking), and §5 discusses sycophancy as a behavioral failure mode that emerges when the generator and evaluator share context. Persona Vectors identifies an explicit "sycophancy" direction in the model's activation space, shows that fine-tuning shifts behavior *along that direction*, and proposes both monitoring (detecting sycophancy emergence during training/deployment) and intervention (suppressing the direction at inference). The paper is by Anthropic Fellows (Chen, Arditi, Sleight, Evans, Lindsey 2025, arXiv:2507.21509), is on the alignment.anthropic.com publication list the walk explicitly scanned, and the sibling user-model lit review already cites it.

The walk's "adjacent work not worth adding" section (CITATION_GRAPH_WALK_REGRESSION.md line 89) explicitly dismisses transformer-circuits.pub / interpretability work as "user-model lit review territory, does not bear on the plan's runtime-cheating-detection threat." This is a procedural compliance failure of the walk: the framing of the search treated interpretability as orthogonal to runtime-cheating-detection, but Persona Vectors is directly relevant to §5's sycophancy discussion regardless of which lit review the interpretability cluster "belongs to." The walker collapsed "interpretability" into "irrelevant to the plan's threat model" and missed the §5 connection.

**Where it lands:** §5's Pan 2024 paragraph (around line 153). A single sentence: "On the model-internal side, Persona Vectors (Chen, Arditi, Sleight, Evans, Lindsey 2025, arXiv:2507.21509) shows that sycophancy is associated with an identifiable direction in activation space whose magnitude shifts under fine-tuning. This is a different mechanism story than Pan 2024's context-sharing-emergence finding — Persona Vectors locates sycophancy in the model's internal representations, Pan 2024 locates it in the iterative-loop's training-time dynamics. Both bear on `pr-98f670e`: the supervisor's verdict aggregation can be skewed by sycophancy-direction activation in the supervisor's own forward pass, independent of whether the loop's context-sharing has primed it."

This is genuinely substantive — it adds a mechanism layer to the §5 sycophancy discussion the post-walk version is missing.

### B1-5. [SUBSTANTIVE] Conclusion's novelty inventory still says the capstone is "the most distinctive thing"

Line 247 (Conclusion): "If the plan succeeds, the capstone is the most distinctive thing it will have shown; if it fails, it is the most likely point of failure." After the walk, this sentence does too much work. The capstone is no longer the most distinctive thing — it's an integration job over AISI Inspect Scout's published seven-step pipeline. The *most distinctive thing* the plan will have shown, if it succeeds, is closer to "the supervisor-architecture story (durable scenarios + work-log priority + scenario-quality supervisor) integrated with the audit machinery the AISI/NIST line already publishes."

The most-likely-point-of-failure framing is still right (the audit is the riskiest piece). But "most distinctive" needs to soften.

**Fix:** "If the plan succeeds, the capstone is the most ambitious published integration of AISI/NIST-line transcript-audit machinery with a continuous-quality loop; if it fails, it remains the most likely point of failure."

### B1-6. [SUBSTANTIVE] SWE-Bench Verified retirement numbers — verified, but the lit review's framing is mildly loose

Verification (WebSearch corroborates the OpenAI blog post via secondary sources): OpenAI retired SWE-Bench Verified on 2026-02-23. The audit covered 138 problematic problems (27.6% of the dataset). At least 59.4% of *audited failed-test cases* were flawed. The breakdown was 49 over-specified tests (35.5%) and 26 unspecified-functionality tests (18.8%), plus reported frontier-model verbatim gold-patch reproduction.

The lit review says (line 53): "an internal audit of the 138 hardest remaining tasks found at least 59.4 percent flawed — 49 with over-narrow tests that rejected functionally-correct solutions, 26 that required undisclosed extra features." The "138 hardest remaining tasks" language slightly editorializes — OpenAI's framing was "problematic problems" (the cases that consistently failed across frontier models), which is closer to "remaining hard" but not identically "the 138 hardest." A pedantic but correctable miss.

**Fix:** "an internal audit of 138 problematic remaining tasks (27.6% of the dataset; these were the problems frontier models consistently failed) found..." This is more precise and adds the 27.6% denominator the reader will want.

### B1-7. [SUBSTANTIVE] The §1 matrix-row "denial at runtime" treats the capstone as the only entry in its quadrant

Lines 76-80, the §1 contamination-defense matrix:
```
denial at runtime                                        ProgramBench
(no internet in sandbox)

detection post-run                                       the plan's capstone
(audit the transcript)
```

After the walk, the bottom row should include AISI Inspect Scout (the actively-shipping detection-post-run pipeline), NIST CAISI's transcript-walk system, and Meerkat (across-traces detection-post-run). The capstone is one of four entries, not the entry. The matrix is the most visually-load-bearing piece of §1; leaving it pre-walk-shaped is a real miss.

**Fix:** "detection post-run / (audit the transcript) — AISI Inspect Scout, NIST CAISI, Meerkat, the plan's capstone."

### B1-8. [SUBSTANTIVE] The §6.3 list closing — five precedents fast, hard to parse

Line 207 lists the precedent map in one sentence: "NIST CAISI and AISI Inspect Scout are the two direct precedents on threat model and audit architecture; Meerkat is the direct precedent on the across-traces cluster-audit axis; the Anthropic overt-saboteur work is the empirical anchor for the audit-plus-human-review pattern; the 2025 Anthropic auditing-agents note and ImpossibleBench are adjacent on different problems."

Five precedents, each with a different role, in one sentence. The reader needs a table or a four-row list, not a comma-spliced paragraph. Compare to the §6.3 matrix-style summary the reader would actually use:

| Precedent | Role | Source |
|-----------|------|--------|
| AISI Inspect Scout | published pipeline the capstone most closely instantiates | AISI/Meridian Labs 2026 |
| NIST CAISI | predecessor methodology that motivated Inspect Scout | NIST 2024-2025 |
| Meerkat | across-traces cluster-audit shape (not single-transcript) | Stein et al. 2026 |
| Anthropic overt-saboteur | empirical anchor for audit-plus-human-review pattern | Anthropic 2026-01 |
| ImpossibleBench / 2025 auditing-agents note | adjacent measurement, different problems | Zhong 2025, Anthropic 2025 |

**Fix:** convert the five-precedent paragraph to this table. It's the densest comparison in the document and prose form fails it.

### B1-9. [SUBSTANTIVE] §6.2's eval-awareness paragraph is now ~5 sentences carrying three distinct ideas

Line 187 packs: (a) the realism-win-rate metric and the 4.6→32.8% lift from deployment-resource grounding (coding-audit-realism paper); (b) Petri 2.0's realism classifier and 47.3% drop in eval-awareness; (c) "eval-awareness is a different failure mode from contamination"; (d) "the capstone inherits some realism by accident; whether the realism-win-rate metric should be adopted explicitly is an open design question." That's a four-claim paragraph that the reader has to parse before reaching §6.3.

The third claim ("different failure mode from contamination") is the one that earns its place in §6 — it justifies why eval-awareness merits a section at all. The other three are detail the section §6.2 didn't previously commit to and that now reads bolted-on. The walker added these because they were forward-walk hits, but the surrounding §6.2 hasn't been restructured to *use* them — the paragraph is dropped in and the section closes.

**Fix:** split into two paragraphs. First paragraph: the existence claim ("eval-awareness is a distinct failure mode from contamination"), with one example metric. Second paragraph: what the plan does or doesn't inherit, ending with the open question. The bolted-on feel goes away if the structural split is made.

### B1-10. [PHRASING] Meerkat's "4x more reward-hacking examples on CyBench" claim

Line 195 cites Meerkat as finding "nearly 4x more reward-hacking examples on CyBench than prior audits." This is the figure the walk pulled from the Meerkat abstract. The lit review repeats it as a published headline finding without flagging that 4x-over-what-baseline depends on which prior audits and which audit budget, and the published Meerkat result is from a preprint that hasn't yet been peer-reviewed. The number is allowed to stand; it's just slightly loose.

**Fix:** "Meerkat reports finding nearly 4x more reward-hacking examples on CyBench than prior audits (per the arXiv preprint; not yet peer-reviewed)..." — a single parenthetical to flag the source quality.

---

## Block 2 — Structure and Readability

### B2-1. [SUBSTANTIVE] Length has crept; the walk's additions are not equally well-integrated

The lit review is now ~9,877 words, up from ~8,748 pre-walk. ~1,100 words added across nine citations. §6 carries most of the additional weight (AISI Inspect Scout's seven-step pipeline description, AISI's 6,390-transcript case study, AuditBench, coding-audit-realism, Petri 2.0, the Meerkat paragraph). §5 carries the AuditBench paragraph (one paragraph, ~150 words). §1 carries the SWE-Bench Verified retirement passage (~80 words).

Read passage-by-passage:
- The §1 SWE-Bench Verified retirement passage (lines 52-53) reads clean. It's a single sentence in the existing paragraph, with the verified numbers.
- The §5 AuditBench paragraph (line 155) reads clean. It's a single coherent unit with an honest narrowing claim.
- §6.3's expansions are the source of the bolt-on feel: lines 191-197 now describe three separate published peers (NIST CAISI, AISI Inspect Scout, the AISI CTF case study) plus Meerkat plus the Anthropic overt-saboteur paragraph plus the closing precedent map. This is the section that carries the walk's heaviest weight and reads as if the walker handed the writer a list to incorporate.

The fix is partly B1-8 (the precedent map should be a table) and partly an audit that all five §6.3 paragraphs have actually been re-threaded around the new prior art, not just appended.

### B2-2. [SUBSTANTIVE] The Conclusion's prior-art inventory sentence (line 247) lists six items in one parenthetical

Line 247: "NIST CAISI and AISI's Inspect Scout pipeline are the two direct precedents on threat model and audit architecture; Meerkat is the across-traces analog; Anthropic's 2026 overt-saboteur note is the empirical anchor for the audit-plus-human-review pattern the plan already adopts; AuditBench's tool-to-agent gap is a published reason to scrutinize the scenario-quality supervisor's verdict-aggregation step (`pr-98f670e`); ImpossibleBench is a structurally adjacent measurement effort whose numbers do not transfer cleanly — none of which is a complete peer."

This is the same five-precedent map as B1-8 but reduplicated in the Conclusion. The reader is being told the same precedent map twice, once in §6.3 and once in the Conclusion, in different orderings.

**Fix:** cut the Conclusion's enumeration to a single sentence — "The capstone integrates the AISI/NIST transcript-audit line (AISI Inspect Scout, NIST CAISI, Meerkat) into a continuous-quality loop, anchored by Anthropic's audit-plus-human-review framework and tempered by AuditBench's tool-to-agent gap caveat and ImpossibleBench's adjacent measurement effort. No complete peer exists." Then point the reader to §6.3 for the table.

### B2-3. [PHRASING] §5's transition into AuditBench is abrupt

Line 153 closes the Pan 2024 paragraph with "...more capable agents reliably exploit reward misspecifications more thoroughly." Line 155 (next paragraph, AuditBench) opens with "A second published note tempers the optimism about evidence-surfacing tools..." But the prior paragraph wasn't *about* optimism about evidence-surfacing tools — it was about reward hacking emerging from context-sharing. The "second published note" framing doesn't match the prior content.

**Fix:** open AuditBench paragraph with "An adjacent failure mode the supervisor design has to consider: AuditBench (alignment.anthropic.com, 2026-03-10) documents..." This bridges from §5's reward-hacking thread to the verdict-aggregation thread cleanly.

### B2-4. [PHRASING] §6.3's "different shape comes from Meerkat" is a flat transition

Line 195: "A different shape comes from Meerkat (Stein, Brown..." After the seven-step AISI Inspect Scout pipeline description and the AISI CTF case study, the reader is now being introduced to a third precedent with no signposting about why this one matters differently.

**Fix:** "Meerkat takes the cluster-audit axis the other two precedents don't (Stein, Brown, ...)." Names the differentiating dimension up front.

### B2-5. [PHRASING] The §6.3 closing-paragraph sentence count

Line 207 is one sentence, 90+ words, three semicolons. It's the densest sentence in the document. Convert to the table from B1-8 or split into three sentences with clearer separation.

---

## Block 3 — Non-Expert Accessibility (load-bearing)

### B3-1. [SUBSTANTIVE] "Tool-to-agent gap" is undefined jargon for the target reader

Line 155: "AuditBench documents a *tool-to-agent gap*: tools that surface accurate evidence in isolation often fail to improve investigator-agent performance, because agents underuse the tools, struggle to distinguish signal from noise, or fail to convert evidence into correct hypotheses."

The phrase "tool-to-agent gap" is novel terminology from the AuditBench paper. The lit review uses italics on first use, but the gloss that follows is itself jargon-heavy (investigator-agent? signal vs. noise?). The non-expert reader needs:

**Rewrite:** "AuditBench documents a *tool-to-agent gap* — a counterintuitive failure: even when you give an AI checker the right evidence in a tidy form (highlighted suspicious actions, summarized tool calls), the checker often fails to use that evidence to reach the right verdict. The bottleneck isn't getting good evidence; it's reading the evidence well. The checker can underuse it, fail to distinguish what matters from what doesn't, or read the evidence and reach the wrong conclusion anyway."

### B3-2. [SUBSTANTIVE] "Realism win rate" is undefined and counterintuitive

Line 187: "introduces *realism win rate* — how often an LLM judge mistakes a synthetic audit transcript for a real deployment transcript — and reports that grounding the auditor in real deployment resources (system prompts, tool definitions, codebases) lifts realism win rate on reward-hacking scenarios from 4.6 to 32.8 percent."

The target reader needs: what is a "synthetic audit transcript"? What is a "deployment transcript"? Why does it matter if a judge mistakes one for the other? The numbers (4.6→32.8%) are anchorless — is 32.8% high or low? Compared to what?

**Rewrite:** "introduces *realism win rate* — a measure of how convincing the audit's mock test scenarios are. The setup: an AI judge sees one transcript from a real production deployment and one from a synthetic test, and tries to guess which is which. A realism win rate of 50% means the judge can't tell them apart (the synthetic test looks fully real). Anthropic reports that grounding the audit's mock environment in real production resources (real system prompts, real tool definitions, real codebases instead of synthetic stand-ins) lifts the realism win rate on reward-hacking scenarios from 4.6 percent (judge nearly always spots the synthetic test) to 32.8 percent (judge fooled about a third of the time)."

That's longer but the original is essentially unreadable for the target audience.

### B3-3. [SUBSTANTIVE] "Investigator agent" / "alignment auditing" / "hidden behaviors" all undefined in one passage

Line 155 (AuditBench): the phrases "alignment-auditing investigator agents," "13 tool configurations," "implanted hidden behaviors," "sycophantic deference, opposition to AI regulation, secret loyalties," all appear in two sentences, all undefined for the target reader.

Line 201 (Anthropic 2025 auditing-agents): "Investigator," "Evaluation Agent," "Breadth-First Red-Teaming Agent," with red-teaming glossed in parens but Investigator and Evaluation Agent not.

A non-expert reading §5-§6 will see ~7 different agent role-names (investigator, evaluator, red-teamer, auditor, scenario-quality supervisor, discovery supervisor, implementation watcher) in close succession with no clear taxonomy.

**Fix:** at the start of §6.3, add a one-paragraph orientation:

> Before walking the precedents, a vocabulary note. *Alignment auditing* is the practice of checking whether a deployed AI behaves as its designers intended — does it lie? favor certain answers? cooperate with users it shouldn't? The audit literature has converged on a small cast of named roles: an *investigator agent* tries to surface the misbehavior by probing the target; an *evaluator* grades the investigator's findings; a *red-teamer* deliberately stress-tests the target by trying to provoke bad behavior. The plan's capstone audit is a single-purpose investigator: it walks the agent's transcript looking for evidence that the agent crossed the rules of the test.

This earns the reader the right to read the rest of §6.3.

### B3-4. [SUBSTANTIVE] "Eval-awareness" is glossed but the gloss is incomplete

Line 187: "eval-awareness, where the model recognizes it is being audited and modulates its behavior."

This is correct but the *consequence* is missing. Why does the reader care? The implied consequence is that the model behaves better during the audit than it does in production — i.e., the audit understates real-world misbehavior. Without that sentence, the reader doesn't know whether eval-awareness is a feature or a bug.

**Fix:** append "...meaning the model can look well-behaved during the audit and misbehave during real use — the audit understates the production failure rate."

### B3-5. [PHRASING] "DSL" gloss inside parens nested inside another parens (line 215)

Line 215: "(DSL — domain-specific language; a small specialized language designed to express one kind of thing precisely, e.g., SQL is a DSL for database queries and CSS is a DSL for styling web pages; AgentSpec's DSL expresses rules an agent must obey at runtime)"

This is exactly the kind of self-aware long parenthetical that Block 4 catches. The target reader gets DSL explained well, but the sentence is unreadable because the parenthetical is half the sentence's content.

**Fix:** break out as a standalone sentence: "AgentSpec is a runtime-enforcement DSL for LLM agents. *DSL* — domain-specific language — is a small specialized language for expressing one kind of thing precisely (SQL is a DSL for database queries, CSS for styling web pages). AgentSpec's DSL expresses rules an agent must obey at runtime."

---

## Block 4 — Prose Craft

### B4-1. The §6.3 sentence "AuditBench's target task is hidden-behavior alignment auditing rather than QA-scenario auditing, so the result does not transfer literally — but the structural concern (a checker reading evidence and aggregating it into a verdict can fail at the aggregation step even when the evidence is good) is shared with the scenario-quality supervisor (`pr-98f670e`)."

90 words, one comma-splice, one em-dash, one parenthetical, one ref. The structural concern is buried in a parenthetical inside an em-dash clause inside a contrastive construction.

**Rewrite:** "AuditBench's target task is hidden-behavior alignment auditing, not QA-scenario auditing — the literal result doesn't transfer. The structural concern does: a checker reading evidence and aggregating it into a verdict can fail at the aggregation step even when the evidence is good. The scenario-quality supervisor (`pr-98f670e`) is on the same axis."

### B4-2. "operational sibling" (line 193)

"AISI Inspect Scout is the operational sibling: an open-source tool, built on Inspect, that defines a seven-step pipeline..."

"Operational sibling" is jargon-flavored. The relationship the lit review wants is: NIST CAISI introduced the methodology; AISI Inspect Scout shipped the tool that implements it.

**Rewrite:** "AISI Inspect Scout is the shipped tool that implements the methodology: an open-source pipeline, built on Inspect, that defines seven steps..."

### B4-3. "Adjacent rather than identical" (line 195)

"...so Meerkat is the published peer for the across-runs cluster-audit shape — adjacent rather than identical to `pr-e2b7fdf`'s single-transcript walk."

"Adjacent rather than identical" is filler. Just say what's different.

**Rewrite:** "...so Meerkat is the published peer for the across-runs cluster-audit shape. The capstone's `pr-e2b7fdf` audits one transcript at a time; Meerkat audits many at once, looking for clusters."

(This second sentence already exists in the lit review at line 195, so "adjacent rather than identical" is also redundant with what immediately precedes it. Cut it as deadwood.)

### B4-4. The §6.2 closing "open design question" hedge

Line 187: "...whether the realism-win-rate metric should be adopted explicitly is an open design question."

"Open design question" is a hedge that ducks the actual question. Either the lit review thinks the capstone should adopt the metric, or it doesn't, or it should say "the plan owes a decision."

**Rewrite:** "The plan should decide whether to adopt the realism-win-rate metric, or to document why a different audit-realism measure better fits the runtime-internet-lookup threat."

### B4-5. "largely an integration job" (line 207)

Conclusion-adjacent phrasing: "The audit in `pr-e2b7fdf` is largely an integration job on top of NIST's and AISI's transcript-walk shape..."

"Largely an integration job" is honest but soft. Either it's an integration job or it's a new methodology. After the walk, the answer is the former — own it.

**Rewrite:** "`pr-e2b7fdf` is an integration job: NIST's and AISI's transcript-walk shape, sharpened by Anthropic's parallel-investigator pattern, complemented by Meerkat's cluster-audit pattern at the across-runs grain, tempered by the open question of LLM-monitor sensitivity in this setting." The "largely" hedge isn't earning its place.

---

## Citation Graph Walk

I ran the step-5 walk per METHODOLOGY.md. Seeds and findings:

**Seeds checked (forward and backward):**

| # | Seed | Forward 12-month walk | Backward references | New citations proposed |
|---|------|------------------------|---------------------|-------------------------|
| 1 | SWE-Bench (Jimenez 2024) | OpenAI Feb 2026 retirement (already cited); Garg "Saving SWE-Bench" (already cited) | clean | none beyond what's there |
| 2 | SWE-agent (Yang 2024) | no architectural successor | clean | none |
| 3 | Self-Refine (Madaan 2023) | converges on Pan 2024 critiques (cited) and Anthropic auditing line (cited) | clean | none beyond Persona Vectors (B1-4) |
| 4 | Reflexion (Shinn 2023) | no new episodic-memory work | clean | none |
| 5 | CodaMosa (Lemieux 2023) | one regression-aware empirical study (not load-bearing per walk) | clean | none |
| 6 | ImpossibleBench (Zhong 2025) | Meerkat (cited) | clean | none |
| 7 | Pan 2024 reward hacking | Anthropic auditing-agent line (cited); Persona Vectors (MISSED) | sycophancy direction work | **Persona Vectors (Chen et al. 2025)** |
| 8 | Sainz 2023 (EMNLP Findings) | Code2Bench (not load-bearing) | clean | none |
| 9 | NIST CAISI | AISI Inspect Scout (cited); AISI CTF case study (cited) | clean | none |
| 10 | AISI Inspect Scout (newly added) | nothing new since 2026-02-25 release | clean | none |
| 11 | AuditBench (newly added) | no follow-up papers yet (2026-03-10 release) | Persona Vectors is cross-citation | reinforces B1-4 |

**Lab pages spot-checked (last 24h):**
- alignment.anthropic.com publication list: nothing posted since coding-audit-realism (2026-03-23) that the walk hadn't already absorbed.
- aisi.gov.uk: nothing posted since Inspect Scout (2026-02-25) and the CTF case study (2025-10-10).
- transformer-circuits.pub: no 2026 Q1-Q2 publication relevant to runtime cheating detection.
- swebench.com/verified.html: leaderboard snapshot 2026-05-14 still cited.

**Walk coverage assessment:** the original walk's coverage is broadly thorough but has one procedural compliance failure (the Persona Vectors miss, B1-4). The walker explicitly dismissed transformer-circuits.pub / interpretability work as "not relevant to runtime-cheating-detection," and that disposition led to the Persona Vectors miss — Persona Vectors is on the alignment.anthropic.com publication list the walker did scan, but the §5 sycophancy connection wasn't surfaced because the walker partitioned interpretability vs. agent-supervision into separate buckets. This is a real procedural finding for future walks: interpretability work can bear on agent-supervision when the agent-side phenomenon (sycophancy in this case) has an internal-representation account.

**Cross-cluster prior art:** Persona Vectors (sibling-lit-review citation) is the cleanest cross-cluster miss; nothing else surfaced.

---

## Convergence Assessment

This review produced **15 findings**: 10 substantive (B1-1 through B1-9 minus B1-10, B2-1, B2-2, B3-1, B3-2, B3-3, B3-4), 5 phrasing-level (B1-10, B2-3, B2-4, B2-5, B3-5, plus the five Block-4 items).

The 10 substantive findings break into three groups:

1. **The walk's framing additions haven't been fully restructured around** (B1-1, B1-3, B1-5, B1-7, B2-1, B2-2). Three top-level summary sentences and one matrix and one Conclusion enumeration continue treating the capstone as alone in its quadrant, when AISI Inspect Scout now lives there. These are fixable in five targeted edits but they are real — the prose's high-level summary frames are inconsistent with the prose's detail frames.

2. **One genuinely missed citation** (B1-4, Persona Vectors) — a procedural walk compliance failure with a specific §5 placement.

3. **Accessibility findings around the walk's new vocabulary** (B3-1, B3-2, B3-3, B3-4) — tool-to-agent gap, realism win rate, investigator agent, eval-awareness — all are post-walk additions that come with their own jargon that hasn't been integrated into the §3-load-bearing accessibility frame the lit review otherwise honors well.

**Verdict: convergence held with caveats. Recommend a Cycle 5 only for the additions' integration.**

The post-walk additions are honest in their narrowing (the AuditBench "doesn't transfer literally" framing is right; the AISI Inspect Scout "operational sibling" framing is right) but the lit review's *high-level framing of its own novelty story* has not been fully restructured around them. This is not a substantive new substance problem — the substance is right, the citations are right, the narrowings are right. It is a structural-and-summary problem: the artifact's lead sentences and headline summaries trade on a pre-walk novelty hierarchy that the walk's additions have collapsed.

The fix is mechanical: edit the §1 matrix bottom row to list four entries, soften the §6 lead paragraph's "most consequential bet" framing, restructure §6.3's lead and closing paragraphs to lead with the published-tool peer, restructure the Conclusion's novelty inventory, add Persona Vectors to §5, and rewrite the three or four §3 jargon glosses.

Cycle 5 should be narrowly scoped: not a full re-review, but a check that the integration edits actually land. The substantive bones of Cycle 3's convergence still hold — the plan's design is well-situated against the literature; the §1 / §2 / §3 / §4 / §7 sections were broadly clean before the walk and remain so. The walk's nine additions concentrated in §5 and §6, and §5 and §6 are where Cycle 5 should focus.

Without those fixes: a reader reaching §1's matrix or §6's opener will read the capstone as more novel than the rest of the document admits. With them: the lit review is fully converged.

---

## What Prior Cycles Missed (Cross-Reference)

Read after writing the independent review above. I scanned `REVIEW_CYCLE_1_LITREVIEW.md`, `REVIEW_CYCLE_2_LITREVIEW.md`, `REVIEW_CYCLE_3_LITREVIEW.md`, `REVIEW_BLOCK4_REGRESSION_LIT.md`, the corresponding response files, and `CITATION_GRAPH_WALK_REGRESSION.md`.

**What this Cycle 4 surfaces that prior cycles did not:**

1. **B1-1 / B1-3 / B1-5 / B1-7 / B2-1 / B2-2** — the post-walk framing-inconsistency cluster. Prior cycles couldn't have caught these because the walk hadn't run yet. Cycle 3 concluded "this is the natural last cycle" with marginal-value-low; the walk subsequently invalidated that conclusion by adding nine citations that demanded restructuring of summary frames, not just appended paragraphs. This is the load-bearing post-walk substantive finding.

2. **B1-4 (Persona Vectors)** — a genuine walk-compliance miss. The walker explicitly dismissed transformer-circuits.pub / interpretability work as out-of-scope; that disposition led to missing a paper that is directly relevant to §5's sycophancy paragraph. The sibling user-model lit review cites Persona Vectors, so the walker had visibility into it; the cross-cluster connection wasn't made.

3. **B3-1 / B3-2 / B3-3 / B3-4** — the walk's new vocabulary (tool-to-agent gap, realism win rate, investigator agent, eval-awareness) didn't receive the same accessibility-pass treatment that Cycle 3 applied to §5 and §6's pre-walk vocabulary. Cycle 3's gloss spine doesn't extend to the walk's additions.

4. **B4-4 — the "open design question" hedge.** The Block-4 review's hedge-cutting pass predates the post-walk additions and didn't catch this new one.

**What prior cycles caught that I echo:**

Cycle 3's substantive critique of the §1 matrix's mischaracterization of the capstone's runtime posture vs. audit posture (B1-8 in Cycle 3) — my B1-7 finding extends this with the post-walk update (the matrix now needs additional bottom-row entries, not just a row-relabel). Cycle 3's verifier-guided-generation finding (B1-9) is already incorporated into the lit review and remains accurate. Cycle 3's accessibility-spine work in §3 is broadly preserved; only the walk's additions need to extend it.

**What prior cycles overstated:**

Cycle 3's convergence claim ("this is the natural last cycle") was right *for the pre-walk artifact*. The walk's additions opened a clearly-defined band of follow-up work that's substantive enough to warrant Cycle 5, but narrow enough that Cycle 5 should be a targeted integration check, not a full re-review.

**Net:** the lit review has remained substantively converged post-walk. The walk added good citations with honest framings. The structural integration of those citations — high-level summary frames, matrix entries, novelty-inventory enumeration — is the work Cycle 5 should finish. After that, the loop genuinely closes.
