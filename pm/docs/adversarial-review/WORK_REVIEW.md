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

### c. Handle inaccessible sources explicitly

If a source is paywalled with no open-access version, no derivative work covering the same ground, and no archived copy, the work cannot be Tier-1 reviewed. Two choices:

- **Drop the work** from the relevance set entirely. The Phase 1 *relevant* verdict was conditional on the work being readable; an unreadable work doesn't anchor anything.
- **Defer the work to a "wanted-but-inaccessible" appendix** in the eventual lit review, with a one-line note on *what citing it would have changed* if access were available. This makes the gap visible to readers and to future iterations (when access may open up).

Do not Tier-1 review a work from its abstract alone and call it deep. Abstract-only is Tier-2 by definition; pretending otherwise reintroduces the over-characterization failure mode the tiering was designed to prevent.

The four pre-flow audits flagged inaccessible sources in-place ("Wiley/PNAS 403s, Princeton UP and SEP 404s"); the new flow does the same prospectively.

### d. Narrow the contribution, don't collapse it — when prior art overlaps

When a Tier-1 review surfaces prior art that overlaps with what the artifact claims is novel — a paper that does *some* of what the artifact does — the review must not capitulate to "the prior art preempts our novelty" *or* hold the line with "we're doing something genuinely new." Both are failure modes the old adversarial-review loop kept producing. The correct move is procedural:

1. **List what the prior art actually does**, sourced from the paper itself (verbatim quote from the abstract where load-bearing claims live, or from the relevant body section for Tier-1 reads). Be precise about variable, methodology, dependent measure, scope, and experimental setup.
2. **List what the artifact does** in the same terms.
3. **Compute the intersection.** That is what the contribution claim has to give up.
4. **Compute the residual** — what the artifact does that the prior art doesn't, as specifically as the artifact actually delivers (not what it aspires to). This is the new, narrower contribution claim.
5. **Produce a synthesis claim that names the residual.** Under the new flow this is the canonical record — the synthesis walker surfaces it for human review, dependents declare against it.

A work-review that accepts prior-art overlap without producing the residual synthesis claim is half-done — it has flagged a problem and not produced the positioning move that resolves it. A work-review that holds the line with "our work is different" without the point-by-point comparison is rejected by the suggester pass (per `SUGGESTION_PASS.md`'s skeptical disposition).

The worked example in repo history is Cycle 3's handling of Choi/Transluce → Deas & McKeown in the user-model lit review: each narrower contribution claim was more defensible than the broader one it replaced. The new flow preserves this discipline by making narrowing-via-synthesis-claim the canonical positioning move.

### e. Surface alternative perspectives and caveats

Does the work contain alternative interpretations, conditions, or caveats that the artifact's intended use elides? Especially: was the work conducted on a model class / domain / regime that does not transfer to the artifact's setting? If yes, that has to enter the per-work entry explicitly — and likely produce a synthesis claim documenting the conditional transfer.

This is the same discipline as audit mode's "surface alternatives" step, applied prospectively rather than retrospectively.

### f. Produce synthesis claims and declare dependencies

Per `SYNTHESIS.md`, after the deep read produce zero or more synthesis claims (positioning / gap / contradiction / terminology) and declare dependencies on prior accepted claims. The per-work entry records both.

If the work would produce a synthesis claim that contradicts a prior accepted claim, *do not* silently override — produce the claim with `**contradicts:** [[prior-claim]]` and let the block-gate route it to human resolution.

Synthesis claim production is the Tier-1 path's defining output. A Tier-1 review with no claims and no dependencies is suspicious — either the work isn't actually load-bearing (downgrade to Tier 2) or the synthesis-shaping content was missed (re-read).

### g. Compose the per-work entry — the lit review material

The entry is structured so Phase 5 can assemble it directly into the lit review prose without re-interpretation:

- **citation header** — author + year + short title + a working clickable link to the source (`[arXiv:XXXX.XXXXX](https://arxiv.org/abs/XXXX.XXXXX)`, DOI URL, publisher page, OpenReview URL, etc.).
- **tier** — 1 or 2.
- **what the work does** (2–4 sentences, longer than Phase 1's summary).
- **load-bearing for the artifact** (which claim / scope condition / methodological choice; one or two sentences). Tier-2 entries may have a single short line here.
- **scope and conditions** (model class, domain, regime — explicit even when obvious; the obvious-elision is the common failure mode).
- **alternative perspectives** (the discussion-section caveats and competing interpretations the artifact's treatment has to engage with). Tier-2 entries may omit.
- **target audience and accessibility notes** — who the lit review's treatment of this work is writing for, and the specific glosses / scale anchors / motivations needed for that audience. Different works in the same lit review legitimately have different target audiences (a foundational philosophy reference is read by a more general reader than a technical methodology paper); the notes are per work. Specifically list: undefined jargon to gloss on first use, prior-art dependencies to summarize inline or mark optional, named entities (papers / tools / methods) that need a one-line "what it is and why we mention it," quantitative claims that need a scale anchor in plain English. Tier-2 entries may use a one-line note.
- **synthesis claims produced** — list of claim ids with their text (full claim recorded in `SYNTHESIS_<artifact>.md`; here just the cross-reference).
- **dependencies declared** — list of claim ids this review depends on, with one-line rationale per dependency.
- **proposed cuts and downgrades of prior material** — the anti-growth action set (see step h).
- **draft prose** (optional, Tier 1) — a 2–3 sentence draft of how the lit review will treat this work, *using the target-audience and accessibility notes above*, ready to drop into Phase 5 assembly. The draft is provisional and gets edited during prose synthesis; producing it now while the source is fresh is cheap and avoids re-reading.

Save the collected reviews to `WORK_REVIEW_<artifact>.md` (per artifact, all iterations append to the same file with iteration markers).

### h. Propose cuts and downgrades — the anti-growth action set

Every Phase 2 work-review's output includes not just *additions* (draft prose, new synthesis claims) but also *cuts and downgrades* of existing material that this new work makes redundant or supersedes. The flow's structural growth bias is countered at the point material lands, not at a Phase 5 cleanup.

For each new relevant work, propose:

- **Prior work-reviews to downgrade.** If this new work covers the same load-bearing ground as a prior Tier-1 entry but at greater scope or rigor, propose dropping the prior entry to Tier 2. If a prior Tier-2 entry is now redundant entirely, propose dropping it to Tier 3 (ref-list-only) or removing it from the lit review's scope. Each downgrade carries rationale ("X et al. 2025 covers the same demand-inference framing with a larger sample and a more recent model; Y et al. 2023 demoted to Tier 2"). These downgrades are synthesis-level positioning moves and route through the synthesis walker for human review.
- **Prior synthesis claims to supersede.** If this work changes a prior claim's framing or makes it conditional, propose marking the prior claim `superseded` with rationale, and produce the replacement claim. The block-gate handles dependent work-reviews that anchored to the old claim — they get re-validated against the replacement.
- **Existing prose to cut.** If draft prose from a prior work-review (or Phase 5 assembled prose) makes a point that this new work makes more crisply, propose cutting the prior prose in favor of the new treatment. Cuts target *redundancy and supersession*, not the new work's own additions.
- **Sections to consolidate.** When two clusters of work-reviews have drifted into making overlapping arguments, propose merging the clusters. Consolidation moves are also synthesis-level — route through the synthesis walker.

If a work-review proposes no cuts or downgrades and adds new material, the suggester pass per `SUGGESTION_PASS.md` flags it: a new work that is genuinely additive (nothing prior is redundant or superseded) is plausible but not the default expectation. The default expectation is that incorporating a new work reshapes the existing treatment, and a work-review whose action set is *pure addition* needs the rationale stated explicitly. This is the per-work counterpart to the old loop's "net-cut once length is flagged" rule, applied prospectively at every work-review rather than retrospectively at Phase 5.

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
