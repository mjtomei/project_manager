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

### Phase 2 — Per-work review (relevant works only)

For each paper rated *relevant* in Phase 1, apply `WORK_REVIEW.md` — the deep-read protocol that **generates the lit review's treatment of the work**. Tier 1 (full text) for the most load-bearing; Tier 2 (abstract + intro + conclusion) for the rest. *Partially relevant* papers get a Tier-2 entry; *not relevant* papers stop here.

This phase is **not auditing** — there's no pre-existing treatment to check against. The deep read produces what the lit review will say about the work, plus the synthesis claims the work supports or produces (see `SYNTHESIS.md`).

**Output:** per-work entries in `WORK_REVIEW_<artifact>.md`, organized by thematic cluster, each carrying what the work does, what's load-bearing for the artifact, scope and conditions, alternative perspectives, the synthesis claims produced or supported, the dependencies declared on prior claims, and (for Tier 1) optional draft prose ready for Phase 5 assembly.

### Phase 3 — Citation crawl + key-phrase search

Per relevant paper, apply `CITATION_CRAWL.md`:
- Google Scholar citation crawl — forward ("cited by", date-sorted) and backward (the paper's own references), at a configurable depth (default depth-1).
- Key-phrase derivation: extract 3–5 phrases characterizing the paper's specific contribution.
- Key-phrase search across non-academic sources — blogs, GitHub, lab notes, OpenReview, alignment forum, vendor research pages.

**Output:** a list of new candidate papers / sources that feed back into Phase 1.

### Interleaved synthesis (active throughout Phases 1–3)

Synthesis is **not** deferred to a final phase. Each Phase 2 audit may produce **synthesis claims** — first-class artifacts that assert something about the literature and that later citations' treatment can depend on. Claims pass an explicit auto-accept / block gate before downstream audits proceed.

The full protocol is in `SYNTHESIS.md`. The short version:

- Each audit may produce zero or more synthesis claims (positioning, gap, contradiction, terminology).
- Each audit declares its dependencies on prior claims by claim id.
- A claim auto-accepts when its supporting audit is `faithful`, it doesn't contradict prior claims, and it's structurally simple. Otherwise it blocks for human review.
- The scheduler runs audits in topological order with respect to synthesis dependencies: a blocked claim stalls only the audits that depend on it; the rest of the pipeline proceeds in parallel.

This is why Phase 5 is pure assembly rather than synthesis-from-scratch — by the time the funnel is empty, every load-bearing synthesis decision has already been made and gated.

### Phase 4 — Iterate to convergence

Loop Phases 1 → 2 (with interleaved synthesis) → 3 until a full iteration's crawls surface zero new candidates that reach the *relevant* threshold in Phase 1 **and** all synthesis claims have a terminal status (no `pending` left). Both conditions are required; the convergence signal alone is necessary but not sufficient (see `SYNTHESIS.md` § Convergence interaction).

Track the iteration count, per-iteration funnel ratio, and per-iteration count of pending synthesis claims in the dashboard — that's the audit trail for *when we stopped looking* and *when synthesis was finalized*.

### Phase 5 — Assembly and prose

Assemble the lit review from the accepted synthesis claims and their supporting citations' audit entries, organized by cluster. **No new synthesis decisions are made here** — Phase 5 is pure assembly of decisions already gated through `SYNTHESIS.md`'s protocol during Phases 1–3.

Run an adversarial-review-cycle pass on the resulting prose using `METHODOLOGY.md` — for prose quality, structural critique, and (load-bearing) accessibility per Block 3. Citation discipline and synthesis discipline are both already enforced upstream, so the older review cycle becomes a prose-and-accessibility pass, not a content or synthesis pass.

#### Net-cut and verbosity discipline (mandatory under Phase 5)

The flow has a structural bias toward growth: every iteration's Phase 2 produces more work-reviews; every accepted synthesis claim is material that wants to live in the lit review's prose. Without an explicit anti-growth rule, the assembled artifact will accumulate exactly the bloat failure mode the old adversarial-review loop kept producing — `METHODOLOGY.md` steps 10–11 documented this with a worked example (`literature-review-living-artifacts.md` grew from ~13k to ~16k words across cycles while its accessibility obligation got worse).

The new flow inherits the same risk. The mandatory disciplines, ported from `METHODOLOGY.md`:

- **Whole-document verbosity pass every Phase 5 iteration.** Independent of whether any reviewer flagged length. The pass reads the document start to finish and, for every paragraph and sentence, asks *can this same point be made with less text?* — applied to original-assembly prose as readily as to recent additions. The pass records its word count before / after and the kinds of cuts made. A pass that found nothing to cut says so explicitly — that is a convergence signal in the same shape as a crawl finding zero new candidates.
- **Net-cut once length is flagged.** Once any reviewer (the Phase 5 adversarial cycle, or the human) flags the assembled artifact as too long, the next iteration's Phase 5 pass **must produce a net word reduction**. New material from newly-accepted synthesis claims goes in tersely (one sentence per claim where possible); every addition is paired with a larger cut; dense survey material moves to an appendix. If the apply pass nets positive or flat, the iteration has failed and is redone.
- **Cut against the whole narrative, not just recent additions.** The net-cut is *not* satisfied by trimming whatever the latest iteration added. Every cut pass is a fresh whole-document hunt for text that is unnecessary or verbose *relative to the point it makes*, regardless of which iteration wrote it.

A document that converges on substance but bloats on length has not converged.

#### Iteration thoroughness — later iterations should be harder, not easier

Ported from `METHODOLOGY.md` step 8: later Phase 5 review iterations should produce more findings than earlier ones with the earlier findings already incorporated. If a later iteration produces fewer findings than its predecessor on the same artifact, two possibilities — the artifact has genuinely improved (convergence signal), or the reviewer is starting to agree with the surrounding context (failure mode). The Phase 5 cycle's review file should state which it believes is happening, with one sentence of justification. The suggester pass on each Phase 5 finding also applies its skeptical disposition (per `SUGGESTION_PASS.md`) — the suggestion is allowed to disagree with the reviewer when the reviewer has slid toward agreement.

## Why this flow

- **Consistent.** Every candidate paper goes through the same scan-then-maybe-detail funnel; nothing is missed by chance.
- **Thorough.** Citation crawl + key-phrase search ensures non-academic and adjacent works surface, not just papers the original author happened to know.
- **Auditable itself.** Each phase produces a doc; each paper has a traceable scan entry, detailed review entry (if relevant), and crawl ancestry. Human intervention can target any phase: skim the scan doc to challenge relevance verdicts; walk the detailed audit to verify characterizations; review the crawl output to challenge what was excluded.
- **Iterative until convergence.** The loop is the discipline. The flow ends when reality (the crawl) says no more relevant work exists.
- **Runnable on bare text.** A topic or research question with no existing bibliography enters the flow at Phase 3's key-phrase derivation; Iteration 1's candidate set is the result. Existing-reference artifacts get the same treatment, layered onto their reference list.

## Companion files

- `INITIAL_SCAN.md` — Phase 1 methodology (abstract + intro + conclusion review, 1–2-sentence summary, relevance verdict).
- `WORK_REVIEW.md` — Phase 2 methodology (deep read of each relevant work; tiered; **generative** — produces the lit review's treatment of the work plus synthesis claims and dependencies per `SYNTHESIS.md`).
- `CITATION_USE_AUDIT.md` — audit-mode variant for pre-flow artifacts (same deep-reading discipline applied in critique mode against an existing lit review).
- `CITATION_CRAWL.md` — Phase 3 methodology (citation graph walk + key-phrase derivation + non-academic search).
- `SYNTHESIS.md` — interleaved-synthesis protocol (claim production, dependency declarations, auto-accept / block gate). Active throughout Phases 1–3.
- `METHODOLOGY.md` — optional Phase 5 prose / structure adversarial-review cycle on the assembled synthesis. Citation and synthesis discipline are no longer this file's job under the new flow.

## Convergence — what to expect

For a moderate-sized literature review:

- Iteration 1: ~30 candidates → ~12 relevant → ~12 detailed reviews → ~80 new candidates from crawl.
- Iteration 2: ~80 candidates → ~18 relevant → ~18 detailed reviews → ~30 new candidates.
- Iteration 3: ~30 candidates → ~4 relevant → ~4 detailed reviews → ~5 new candidates.
- Iteration 4: ~5 candidates → 0 relevant → convergence.

Total relevant works: ~34. Total scans: ~145. The funnel ratio tightens across iterations; convergence is typically reached in 3–5 iterations. Departures from this shape are themselves signal — a flat funnel ratio across iterations suggests the relevance criterion is too lax; a vanishing iteration-1 set suggests the seed was too narrow.
