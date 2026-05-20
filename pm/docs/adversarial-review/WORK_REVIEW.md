# Per-Work Review (methodology)

Phase 2 of the literature review flow (see `LITERATURE_REVIEW_FLOW.md`). The detailed deep read of each work Phase 1's initial scan rates *relevant* — and the **primary source of material** for the eventual lit review.

This is not an audit. There is no pre-existing artifact to check against. The per-work review *generates* the lit review's treatment of the work: what the work does, what's load-bearing for the artifact's argument, how the artifact will position itself relative to it, and what synthesis claims the work produces or supports. Composition in Phase 5 is *assembly* of these reviews, not interpretation of them.

(For the auditing of an existing pre-flow lit review against its sources, see `CITATION_USE_AUDIT.md` — the same deep-reading discipline applied in critique mode rather than generative mode.)

## Input

A work classified *relevant* (or *partially relevant*) by Phase 1, with its citation header + 1–2-sentence scan summary + relevance rationale. Plus the in-progress `SYNTHESIS_<artifact>.md` (the accumulated synthesis claims so far) — the prior-claim context the review needs to declare dependencies against.

## Procedure

### a. Tier the work by depth

Not every relevant work gets the deepest read.

- **Tier 1 — deep read.** The most load-bearing works for the artifact's argument: those that preempt or anchor a novelty claim, provide empirical support a synthesis claim will rest on, anchor a methodological choice, or are the nearest published peer on a load-bearing variable. Full-text read (or all relevant chapters / sections for long papers). Aim for ~50 Tier-1 reviews for a moderate-sized lit review; if many more appear load-bearing, sharpen the criterion.
- **Tier 2 — abstract-level read.** Works that support but do not anchor the argument — *partially relevant* from Phase 1 or *relevant-but-secondary*. Abstract + intro + conclusion sufficient. Per-work entry is denser; usually no synthesis claims produced (claims are mostly the Tier-1 output).

Document the tiering up front in the review doc. Tier is explicit on every entry.

### b. Deep-read at the right depth

For Tier 1, read the full text. The abstract elides methodological scope, ground-truth construction, model class, domain restriction, and alternative perspectives that live in the paper's own discussion. Those are exactly the load-bearing details for *generating* the lit review's treatment — not just for catching an existing treatment's errors.

For Tier 2, the abstract is sufficient. The check is: does the artifact's eventual one-line treatment of the work hold up against the abstract?

For each work regardless of tier, capture:
- **What the work does** (method + key result, longer than the Phase 1 summary — 2–4 sentences).
- **What's load-bearing** for the artifact's argument (which specific claim, scope condition, or methodological choice the artifact will use this work to anchor).
- **Scope and conditions** (model class, domain, regime). These propagate into the synthesis claims the work supports — eliding them is the common Tier-1 failure mode.

### c. Surface alternative perspectives and caveats

Does the work contain alternative interpretations, conditions, or caveats that the artifact's intended use elides? Especially: was the work conducted on a model class / domain / regime that does not transfer to the artifact's setting? If yes, that has to enter the per-work entry explicitly — and likely produce a synthesis claim documenting the conditional transfer.

This is the same discipline as audit mode's "surface alternatives" step, applied prospectively rather than retrospectively.

### d. Produce synthesis claims and declare dependencies

Per `SYNTHESIS.md`, after the deep read produce zero or more synthesis claims (positioning / gap / contradiction / terminology) and declare dependencies on prior accepted claims. The per-work entry records both.

If the work would produce a synthesis claim that contradicts a prior accepted claim, *do not* silently override — produce the claim with `**contradicts:** [[prior-claim]]` and let the block-gate route it to human resolution.

Synthesis claim production is the Tier-1 path's defining output. A Tier-1 review with no claims and no dependencies is suspicious — either the work isn't actually load-bearing (downgrade to Tier 2) or the synthesis-shaping content was missed (re-read).

### e. Compose the per-work entry — the lit review material

The entry is structured so Phase 5 can assemble it directly into the lit review prose without re-interpretation:

- **citation header** — author + year + short title + a working clickable link to the source (`[arXiv:XXXX.XXXXX](https://arxiv.org/abs/XXXX.XXXXX)`, DOI URL, publisher page, OpenReview URL, etc.).
- **tier** — 1 or 2.
- **what the work does** (2–4 sentences, longer than Phase 1's summary).
- **load-bearing for the artifact** (which claim / scope condition / methodological choice; one or two sentences). Tier-2 entries may have a single short line here.
- **scope and conditions** (model class, domain, regime — explicit even when obvious; the obvious-elision is the common failure mode).
- **alternative perspectives** (the discussion-section caveats and competing interpretations the artifact's treatment has to engage with). Tier-2 entries may omit.
- **synthesis claims produced** — list of claim ids with their text (full claim recorded in `SYNTHESIS_<artifact>.md`; here just the cross-reference).
- **dependencies declared** — list of claim ids this review depends on, with one-line rationale per dependency.
- **draft prose** (optional, Tier 1) — a 2–3 sentence draft of how the lit review will treat this work, ready to drop into Phase 5 assembly. The draft is provisional and gets edited during prose synthesis; producing it now while the source is fresh is cheap and avoids re-reading.

Save the collected reviews to `WORK_REVIEW_<artifact>.md` (per artifact, all iterations append to the same file with iteration markers).

## Why this differs from auditing

Auditing catches errors in a treatment that already exists. Per-work review produces the treatment. The discipline is the same — full-text read, scope-and-conditions explicit, alternative perspectives surfaced — but the output is *new material* rather than *corrections to existing material*.

This is also why synthesis-claim production lives here and not in the audit protocol. The claims are the load-bearing decisions the artifact's argument is built from; they have to be produced as the source material is being read, not retrofitted after a draft has been written.

## Parallelization

Per-work reviews are parallelizable subject to the synthesis dependency graph. Within a tier-1 cluster of works that share dependencies on the same upstream claims, run them in parallel; across clusters where Cluster B's reviews depend on synthesis claims Cluster A produces, sequence them. The flow scheduler handles this automatically based on declared dependencies (see `SYNTHESIS.md` § Topological ordering).

For Tier-2 reviews, parallelize freely — Tier-2 entries rarely produce claims and rarely declare dependencies.

## Companion files

- `LITERATURE_REVIEW_FLOW.md` — the overall pipeline; this file is the Phase 2 methodology.
- `INITIAL_SCAN.md` — Phase 1 (the funnel that decides which works reach this protocol).
- `SYNTHESIS.md` — claim production, dependency declaration, auto-accept / block gate. Half the output of every Tier-1 review goes here.
- `CITATION_CRAWL.md` — Phase 3 (crawl that feeds the next iteration's Phase 1).
- `CITATION_USE_AUDIT.md` — the audit-mode variant for pre-flow artifacts.
