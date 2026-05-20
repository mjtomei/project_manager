# Literature Review Flow

The end-to-end pipeline for producing a literature review using this repo's methodology. This flow **replaces** the earlier draft-then-review-then-audit pipeline with a more consistent, thorough, and auditable iterative process built *from sources* rather than from an LLM first draft.

The flow is runnable on any text artifact — with or without existing references — and on a bare topic or research question. It produces a literature review whose every citation has been seen at least once, whose relevant works have been read in full, and whose adjacent prior art has been surfaced by walked citation graphs and key-phrase searches across both academic and non-academic sources.

## Phases

### Phase 1 — Initial scan

**Input:** the artifact (a literature review draft, a research plan, a topic seed, or a bare research question), plus a candidate paper set:
- the artifact's existing inline references + bibliography, if any;
- *and / or* key-phrase-derived seed papers from Phase 3 applied to the artifact text, if there are no references.

**Process:** apply `INITIAL_SCAN.md` to each candidate.
- Read abstract + introduction + conclusion only.
- Produce a 1–2 sentence summary: what the paper does, the key result.
- Tag each candidate with a relevance verdict — *relevant / partially relevant / not relevant*.

**Output:** an initial-scan doc with one entry per candidate (link + summary + verdict).

The scan is the *funnel*. Most candidates get a few minutes; the relevant ones escalate.

### Phase 2 — Detailed review (relevant works only)

For each paper rated *relevant* in Phase 1, apply `CITATION_USE_AUDIT.md` — the full audit protocol, tiered by load-bearing significance. Tier 1 (deep, full-text read) for the most load-bearing; Tier 2 (abstract verification) for the rest. *Partially relevant* papers get a Tier-2 entry; *not relevant* papers stop here.

**Output:** per-paper detailed audit entries, organized by thematic cluster.

### Phase 3 — Citation crawl + key-phrase search

Per relevant paper, apply `CITATION_CRAWL.md`:
- Google Scholar citation crawl — forward ("cited by", date-sorted) and backward (the paper's own references), at a configurable depth (default depth-1).
- Key-phrase derivation: extract 3–5 phrases characterizing the paper's specific contribution.
- Key-phrase search across non-academic sources — blogs, GitHub, lab notes, OpenReview, alignment forum, vendor research pages.

**Output:** a list of new candidate papers / sources that feed back into Phase 1.

### Phase 4 — Iterate to convergence

Loop Phases 1 → 2 → 3 until a full iteration's crawls surface zero new candidates that reach the *relevant* threshold in Phase 1. That zero is the convergence signal.

Track the iteration count and per-iteration funnel ratio in the scan doc — it's the audit trail for *when we stopped looking*.

### Phase 5 — Synthesis and prose

Assemble the relevant works into the literature review document, organized by cluster. Each cluster's entries are drawn from Phase 2's detailed reviews; prose connecting them surfaces the artifact's positioning.

Optionally, run an adversarial-review-cycle pass on the resulting prose using `METHODOLOGY.md` — for prose quality and structural critique only. Citation discipline is already enforced by Phases 1–3, so the older review cycle becomes a prose pass, not a content pass.

## Why this flow

- **Consistent.** Every candidate paper goes through the same scan-then-maybe-detail funnel; nothing is missed by chance.
- **Thorough.** Citation crawl + key-phrase search ensures non-academic and adjacent works surface, not just papers the original author happened to know.
- **Auditable itself.** Each phase produces a doc; each paper has a traceable scan entry, detailed review entry (if relevant), and crawl ancestry. Human intervention can target any phase: skim the scan doc to challenge relevance verdicts; walk the detailed audit to verify characterizations; review the crawl output to challenge what was excluded.
- **Iterative until convergence.** The loop is the discipline. The flow ends when reality (the crawl) says no more relevant work exists.
- **Runnable on bare text.** A topic or research question with no existing bibliography enters the flow at Phase 3's key-phrase derivation; Iteration 1's candidate set is the result. Existing-reference artifacts get the same treatment, layered onto their reference list.

## Companion files

- `INITIAL_SCAN.md` — Phase 1 methodology (abstract + intro + conclusion review, 1–2-sentence summary, relevance verdict).
- `CITATION_USE_AUDIT.md` — Phase 2 methodology (the full detailed audit; tiered, with standalone audit-doc output).
- `CITATION_CRAWL.md` — Phase 3 methodology (citation graph walk + key-phrase derivation + non-academic search).
- `METHODOLOGY.md` — optional Phase 5 prose / structure adversarial-review cycle on the assembled synthesis. Citation discipline is no longer this file's primary job under the new flow.

## Convergence — what to expect

For a moderate-sized literature review:

- Iteration 1: ~30 candidates → ~12 relevant → ~12 detailed reviews → ~80 new candidates from crawl.
- Iteration 2: ~80 candidates → ~18 relevant → ~18 detailed reviews → ~30 new candidates.
- Iteration 3: ~30 candidates → ~4 relevant → ~4 detailed reviews → ~5 new candidates.
- Iteration 4: ~5 candidates → 0 relevant → convergence.

Total relevant works: ~34. Total scans: ~145. The funnel ratio tightens across iterations; convergence is typically reached in 3–5 iterations. Departures from this shape are themselves signal — a flat funnel ratio across iterations suggests the relevance criterion is too lax; a vanishing iteration-1 set suggests the seed was too narrow.
