# Initial Scan (methodology)

Phase 1 of the literature review flow (see `LITERATURE_REVIEW_FLOW.md`). The fast funnel: every candidate paper gets a brief look so that the detailed audit (Phase 2) targets only what matters.

## Input

- The artifact (a literature review draft, a research plan, a topic seed, or a bare research question).
- A candidate paper set:
  - the artifact's existing inline references + bibliography, if any;
  - and / or key-phrase-derived seed papers from `CITATION_CRAWL.md` applied to the artifact text (for artifacts without existing references, or for the first iteration of a from-scratch flow);
  - and / or new candidates produced by the previous iteration's Phase 3 crawl.

## Per-candidate procedure

For each candidate:

### 1. Read abstract + introduction + conclusion only

Skip the body. These three sections together capture what the paper does, its key contribution, and the most prominent caveats. Body details belong to Phase 2 for the papers that survive this filter.

### 2. Produce a 1–2 sentence summary

Capture two things only:
- What the paper does (its method or claim).
- The key result.

An optional third sentence is allowed if a scope condition (model class, domain, regime) is the load-bearing reason the paper either transfers or does not transfer to the artifact's setting. Otherwise omit.

The summary is for the next-step relevance judgement and for the eventual synthesis. It is **not** a critique or audit — that belongs to Phase 2 for the works that proceed.

### 3. Assign a relevance verdict

Each entry gets one of:

- **relevant** — the paper bears directly on the artifact's argument or topic: it preempts a novelty claim, provides load-bearing empirical support, anchors a methodological choice, or is the nearest published peer on a load-bearing variable. Proceed to Phase 2 (detailed audit) and Phase 3 (citation crawl).
- **partially relevant** — adjacent or supporting; the artifact may cite it in passing without the argument depending on the characterization. Proceed to a Tier-2 entry under `CITATION_USE_AUDIT.md` if the artifact uses it; skip Phase 3's crawl.
- **not relevant** — out of scope for the artifact's argument or topic. Note briefly why so future iterations don't re-surface it (e.g., "different domain — vision, not LLMs"; "subsumed by [X]").

Make the relevance criteria **explicit** at the top of the scan doc, so the verdict is reproducible and contestable. Different artifacts may legitimately draw the relevance line in different places; the scan doc has to say where the line was drawn.

## Output

Save the scan to its own file — for example `pm/docs/adversarial-review/INITIAL_SCAN_<artifact>_iter<N>.md`. Each entry contains:

- **citation header** — author + year + short title + a working clickable link to the source (`[arXiv:XXXX](https://arxiv.org/abs/XXXX)`, DOI URL, publisher page, OpenReview URL, etc.).
- **summary** — 1–2 sentences (per the procedure above).
- **verdict** — relevant / partially relevant / not relevant.
- **rationale** — one short line explaining the verdict against the stated criteria.

At the top of the file, before the entries:

- The artifact under review (path + brief description).
- The iteration number.
- The candidate set source (existing references / Phase 3 crawl from iteration N-1 / key-phrase derivation from the artifact text).
- The explicit relevance criteria for this scan.

## Why a couple of sentences and not more

The point of Phase 1 is throughput. Detailed prose lives in Phase 2 (the audit). A multi-paragraph summary at this stage is wasted effort because most candidates will be filtered out.

## Why every candidate, no exceptions

Skipping a candidate at Phase 1 means it never enters the funnel. Every candidate that arrives — from the artifact's existing references, from a citation crawl, or from a key-phrase search — must get a scan entry, even a brief one. The discipline is what makes the audit reproducible and the convergence signal trustworthy.

## Parallelization

Initial scans are embarrassingly parallel — chunk the candidate set by 10–20 papers per agent and run them concurrently. Each agent writes a section of the iteration's scan doc; the author concatenates sections at the end.
