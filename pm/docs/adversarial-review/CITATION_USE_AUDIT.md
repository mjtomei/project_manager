# Citation-Use Audit (methodology — audit mode for pre-flow artifacts)

The dedicated full-text citation **audit** of an existing literature review whose generation pre-dated the new flow. Catches over-characterizations, missed alternative perspectives, and citation-vs-source mismatches that slipped past blind adversarial-review cycles.

**This is not the Phase 2 methodology for the new literature review flow.** Under that flow there is no existing treatment to audit — Phase 2 *generates* the treatment from a deep read. See `WORK_REVIEW.md` for the generative variant. The two files share most of the deep-reading discipline; the difference is whether the per-work entry critiques an existing passage or produces new lit-review material.

Used in this repo to audit the four pre-flow lit reviews (`literature-review.md`, `literature-review-user-model.md`, `literature-review-user-model-extension.md`, `literature-review-living-artifacts.md`) — see `CITATION_AUDIT_*.md` for the resulting audit docs.

Companion to `WORK_REVIEW.md` (generative variant under the new flow), `INITIAL_SCAN.md`, `CITATION_CRAWL.md`, `SYNTHESIS.md`, and `METHODOLOGY.md`.

## When to run

- **Between cycles, after a large citation expansion** — for example, the bulk addition of references via a lit-search agent. The first-pass audit catches abstract-level over-characterization before the next blind reviewer sees the doc.
- **As the final pass**, once iterative adversarial-review cycles have converged on substance and structure (METHODOLOGY's "stop when findings get pedantic" signal). The final pass reads full papers on every load-bearing citation.
- The audit can run multiple times in a project's lifetime; the final one is the publication-readiness gate.

## What it does — and doesn't

The audit verifies that **every load-bearing citation is characterized faithfully against the actual source**, and that **significant alternative perspectives or caveats in cited works are represented** in the artifact's text.

It does *not* re-find missed prior art — that is the citation-graph walk (METHODOLOGY step 5). The two are complementary: the walk finds what should be cited; the audit checks that what *is* cited is used faithfully.

## Protocol

### a. Audit every citation. Tier by depth — make the tier explicit.

**Every citation in the artifact gets audited.** To make this tractable on a moderate-sized literature review, sort citations into tiers by load-bearing significance and apply different audit depths. **The tier must be explicit on each entry** so the artifact's author can see (and contest) the scoping decisions.

- **Tier 1 — Deep audit.** The most load-bearing citations: those whose accurate characterization the argument explicitly depends on (preempts/anchors a novelty claim, provides empirical support for a load-bearing assertion, anchors a methodological choice, invoked across multiple sections). For each Tier-1 citation, do a **full-text read** (or the relevant chapters / sections where the paper is long) and produce the full per-citation entry (doc passage → source content with verbatim quote → verdict → proposed rewrite). For a moderate-sized literature review, aim for **~50 Tier-1 entries**. If there appear to be more, that is a triage signal — sharpen the load-bearing test until ~50 survive.
- **Tier 2 — Light audit.** Citations that support but do not anchor the argument — background, "as also noted by", referenced once in passing without the argument depending on the characterization. Do an **abstract-level verification** (does the artifact's brief characterization match what the abstract says; flag obvious mischaracterizations) and produce a brief entry (doc passage → abstract gloss → verdict). No full-text read required. Propose a rewrite only if the issue is egregious.
- **Tier 3 — Reference-list-only check (optional).** Citations that appear only in the reference list, with no inline use in the argument. Verify the entry exists at the claimed arXiv ID / DOI; one-line entry is sufficient. (If your audit pass turns up zero such entries, the artifact's references and inline citations are in good correspondence — say so.)

Document the **tiering criteria** up front in the audit doc — under a heading like "Tiering" — listing the rules you used to assign citations to tiers. Then list the citations in each tier explicitly.

### b. Verify against the source — at the right depth for each tier

For **Tier 1**, read the full text. The abstract routinely elides the methodological scope, ground-truth construction, model class, domain restriction, and the alternative perspectives that live in the paper's own discussion section. Those are exactly the load-bearing details for faithfulness.

For **Tier 2**, the abstract is sufficient. The check is: does the artifact's brief characterization match what the abstract says?

For each citation regardless of tier:
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

- **citation header** — author + year + short title + a working clickable link to the source. Use the markdown form `[arXiv:XXXX.XXXXX](https://arxiv.org/abs/XXXX.XXXXX)` for arXiv preprints; `[doi:10.NNNN/...](https://doi.org/10.NNNN/...)` for journal articles; an OpenReview URL for workshop submissions; a publisher catalog or stable archive page for books. The link is the walker's path to verify any claim against the source on demand without leaving the audit doc.
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
