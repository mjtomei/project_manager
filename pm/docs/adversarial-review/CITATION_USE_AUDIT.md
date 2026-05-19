# Citation-Use Audit (methodology)

The dedicated full-text citation audit. Run between adversarial review cycles after a large citation expansion, or as the final pass before a literature review is considered complete. Companion to `METHODOLOGY.md` (the per-cycle adversarial-review protocol) and `LITERATURE_REVIEW_FLOW.md` (the end-to-end flow).

## When to run

- **Between cycles, after a large citation expansion** — for example, the bulk addition of references via a lit-search agent. The first-pass audit catches abstract-level over-characterization before the next blind reviewer sees the doc.
- **As the final pass**, once iterative adversarial-review cycles have converged on substance and structure (METHODOLOGY's "stop when findings get pedantic" signal). The final pass reads full papers on every load-bearing citation.
- The audit can run multiple times in a project's lifetime; the final one is the publication-readiness gate.

## What it does — and doesn't

The audit verifies that **every load-bearing citation is characterized faithfully against the actual source**, and that **significant alternative perspectives or caveats in cited works are represented** in the artifact's text.

It does *not* re-find missed prior art — that is the citation-graph walk (METHODOLOGY step 5). The two are complementary: the walk finds what should be cited; the audit checks that what *is* cited is used faithfully.

## Protocol

### a. Distinguish load-bearing from supporting citations

Load-bearing citations are the ones the argument depends on characterizing correctly: they preempt or anchor a novelty claim, provide empirical support for a load-bearing assertion, or anchor a methodological choice. Supporting citations are background or "as also noted by" references.

The audit focuses on the load-bearing set; supporting citations get a lighter check.

### b. Verify against the source — at the right depth

For supporting citations, the abstract is usually sufficient.

**For load-bearing citations, read the full text** — or the relevant chapters / sections where the paper is long. The abstract routinely elides the methodological scope, ground-truth construction, model class, domain restriction, and the alternative perspectives that live in the paper's own discussion section. Those are exactly the load-bearing details for faithfulness.

For each load-bearing citation:
- Does the artifact's text match what the work actually claims and shows?
- Are we over- or under-characterizing the *strength*, *scope*, or *conditions* of the result?
- A common failure mode after a lit-search-driven expansion: the agent's one-line characterization elides a model-class limitation, a domain restriction, or a regime caveat.

### c. Surface alternative perspectives and caveats

Does the cited work contain significant alternative interpretations, conditions, or caveats that bear on the argument and that the artifact does not represent?

Especially: was the work conducted on a particular model class / domain / regime that does not transfer to the artifact's setting? If yes, that needs to be stated in the artifact, not left implicit.

### d. Propose substantive changes — not just verdicts

For each finding, propose the *actual rewording* (or, where load-bearing, the *actual restructure*) the artifact needs. A finding that says "over-characterized" without proposing the corrected text is half-done. The proposed change should be ready to apply verbatim.

### e. Output a standalone review doc

Save the audit to its own file — for example `pm/docs/adversarial-review/CITATION_AUDIT_<artifact>_<context>.md` — structured per citation:

- **doc passage as currently written** (verbatim quote from the artifact)
- **what the source actually says** (verbatim quote on load-bearing claims; otherwise paraphrase with section reference)
- **verdict** (faithful / over-characterizes / under-characterizes / mischaracterizes)
- **proposed rewrite** (verbatim — what the artifact author pastes in)

Burying the audit in a response file loses the structured per-citation form and makes it hard to track which proposed rewrites were applied. A separate file lets the artifact's author walk through line by line.

## Parallelization

For a moderate-sized review, chunk citations thematically (8–12 per audit agent, 4 parallel agents). Each agent writes one section of the output doc; sections are merged by the artifact's author. Chunks should be roughly orthogonal to avoid two agents writing different verdicts for the same citation.

## Why this is necessary

Lit-search agents and reviewer summaries routinely over-characterize prior art in subtle ways — eliding a model-class limitation, a regime caveat, or a domain restriction. These slip past blind reviewers in subsequent cycles because the reviewer is checking against the artifact's text rather than the cited source's actual content.

Failure-mode history in this repo:
- **The "near-twin" framing of Cheng et al. 2026** (Cycle 9–10 user-modeling extension): the doc collapsed an attribute-vs-intent distinction the source preserved; caught only on RC discussion, not by the blind reviewer.
- **The "largely pre-empted" framing of Arora 2023 / Ahmed & Singh 2026** (Cycle 11 precursor): the doc inherited a lit-search agent's verdict without independently reading the figures; the figure-semantics critique was incorrect.
- **The "REINFORCE differential against natural text" framing of Quiet-STaR** (Cycle 11 precursor): mischaracterized the reward (which is sibling-rationale-baselined REINFORCE with m-token lookahead, not a likelihood differential against natural text).

In each case the audit — not the blind reviewer — was the discipline that caught the error.
