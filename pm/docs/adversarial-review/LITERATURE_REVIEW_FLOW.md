# Literature Review Flow

The end-to-end pipeline for producing a literature review using this repo's methodology. This flow **replaces** the earlier draft-then-review-then-audit pipeline with a more consistent, thorough, and auditable iterative process built *from sources* rather than from an LLM first draft.

The flow is runnable on any text artifact — with or without existing references — and on a bare topic or research question. It produces a literature review whose every citation has been seen at least once, whose relevant works have been read in full, and whose adjacent prior art has been surfaced by walked citation graphs and key-phrase searches across both academic and non-academic sources.

## Phases

### Phase 0 — Cycle-opening monolithic review

Every iteration begins with **one generic review agent** that reads the current state of the artifact (in iteration 1: the target text / plan / topic; in iteration N > 1: the in-progress lit review plus all prior work-reviews, synthesis claims, and the notes file) and produces a **single monolithic review document** — `CYCLE_REVIEW_<artifact>_iter<N>.md` — with many findings.

This is the direct analog of the old adversarial-review loop's `REVIEW_CYCLE_N.md`. Same shape: a fresh blind Claude session, the same skeptical disposition (per `SUGGESTION_PASS.md`), the same kind of monolithic output covering substance, structure, coverage gaps, faithfulness concerns about prior work-reviews, accessibility flow, narrative coherence, verbosity overview, and the synthesis-claim coherence-as-worldview check. The eight standing whole-document tasks are the questions this reviewer answers.

**What's new is what happens to the findings.** The old loop fed `REVIEW_CYCLE_N.md` into a single sequential response session that handled every finding in one pass. The new flow routes findings into **per-entry queues** that drive parallel sub-agent work for the rest of the iteration:

- *Coverage gap* → key-phrase seed appended to the iteration's Phase 3 crawl input set, and to the Phase 1 candidate set if the reviewer named specific works.
- *Novel candidate work* the reviewer surfaces → entry in iteration's Phase 1 candidate set.
- *Faithfulness concern about a prior work-review* → re-audit task queued for the work-review walker; the prior work-review's status flips to `pending re-audit` until the new agent runs.
- *Synthesis-claim contradiction or incoherence* → proposed `contested` or `superseded` status on the affected claim in the synthesis walker.
- *Cluster reorganization* → proposed work-relocation moves in the work-review walker.
- *Prose edit* → proposed-edit entry in the proposed-edits walker.
- *Verbosity finding* → proposed cut entries in the proposed-edits walker, routed to the cluster the reviewer named.

Each routed finding lands as a response-block entry in its target walker, with the monolithic review's rationale as the suggester-rationale (the suggester pass per entry adds independent verification per `SUGGESTION_PASS.md`). Findings without a walker-typed action stay in the cycle-review view as general observations.

The cycle-opening review is what tells iteration N what work to do. The per-entry agents that fire in Phases 1–3 are driven by the union of (the prior iteration's crawl output) and (this cycle's monolithic review's findings).

In auto-run mode, the monolithic review's findings auto-accept (subject to block criteria) and immediately fan out to per-entry queues; in human-reviewed mode the cycle-review walker is the human's first stop each iteration before specific tasks fire.

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

Loop Phase 0 → Phases 1 → 2 (with interleaved synthesis) → 3 until **three conditions all hold simultaneously**:

1. The iteration's crawls surfaced zero new candidates that reached the *relevant* threshold in Phase 1.
2. All synthesis claims have a terminal status (no `pending` left). See `SYNTHESIS.md` § Convergence interaction.
3. The iteration's Phase 0 monolithic review produced no material findings — the reviewer's verdict is "the artifact is at convergence; nothing further to add."

Track the iteration count, per-iteration funnel ratio, per-iteration count of pending synthesis claims, and per-iteration Phase-0 finding count in the dashboard. That's the audit trail for *when we stopped looking*, *when synthesis was finalized*, and *when the monolithic reviewer ran out of things to flag*.

#### The eight standing tasks (Phase 0's question set)

Phase 0's reviewer answers eight standing whole-document tasks in one monolithic pass. These are the structure of Phase 0's question prompt, not a separate phase:

- **Structural coherence.** Do the clusters still make sense given the latest iteration's additions? Are cluster boundaries well-drawn? Should any work-review move clusters?
- **Cluster-to-cluster flow.** Does each cluster set up the next? Are there abrupt transitions or missing connective tissue between clusters? Propose specific bridging prose where needed.
- **Section flow within clusters.** Within each cluster, is the order of works coherent? Does each work's treatment lead into the next?
- **Synthesis-claim coherence.** Do the accepted synthesis claims still cohere as a worldview? Are there latent tensions or contradictions prior iterations' work-reviews surfaced but didn't resolve? Surface them as proposed `contested` claims for the synthesis walker.
- **Coverage gaps.** Are there thematic areas the artifact's argument needs but that the prior iteration's crawl didn't surface? Each gap becomes a key-phrase seed for *this* iteration's Phase 3 and a candidate entry in Phase 1 if the reviewer named specific works.
- **Whole-document verbosity overview.** Are any clusters growing unduly long? Is redundancy creeping in across clusters that no per-work cut-and-downgrade action caught? Propose cluster-level cuts.
- **Accessibility flow.** Even with per-work accessibility notes (per `WORK_REVIEW.md` step g), the overall narrative still needs to be navigable — transitions between works of different audiences, glossary consistency across clusters, the artifact's overall reading-pace. Propose adjustments.
- **Narrative coherence.** Read the assembled draft as a reader would (with the latest accepted material integrated). Does the argument hold together? Where does it stall?

The reviewer also (per `SUGGESTION_PASS.md` § Phase 0) identifies novel candidate works the prior iteration's crawl didn't surface, triggers re-audits on prior work-reviews it finds suspect, and recommends the convergence verdict when applicable.

**Dispatch.** Phase 0 fires automatically at the start of each iteration's ready-task batch (per `plan-litreview-ui.md` § Ready-task execution). The "Fire ready tasks" button generates a prompt containing both Phase 0's reviewer pass and the iteration's specific per-entry tasks; the session launches Phase 0's reviewer in parallel with whatever entry-writing work was already queued from the prior iteration's findings. Phase 0 fires every iteration, even when no specific tasks are queued, so the button is meaningful at every point in an in-progress flow.

### Phase 5 — Assembly and prose

Assemble the lit review from the accepted synthesis claims and their supporting citations' audit entries, organized by cluster. **No new synthesis decisions are made here** — Phase 5 is pure assembly of decisions already gated through `SYNTHESIS.md`'s protocol during Phases 1–3.

Optionally, run an adversarial-review-cycle pass on the resulting prose using `METHODOLOGY.md` — for prose quality and structural critique. Citation discipline, synthesis discipline, **and accessibility** are all already enforced upstream (accessibility lives on the per-work review per `WORK_REVIEW.md`'s target-audience and gloss-notes fields), so the older review cycle is a prose-cleanup pass on an already-disciplined artifact.

#### Anti-growth discipline is in Phase 2, not Phase 5

The flow has a structural bias toward growth: every iteration's Phase 2 produces more work-reviews; every accepted synthesis claim is material that wants to live in the lit review's prose. Without an explicit anti-growth rule, the assembled artifact will accumulate exactly the bloat failure mode the old adversarial-review loop kept producing (`literature-review-living-artifacts.md` grew from ~13k to ~16k words across cycles while its readability got worse).

The new flow handles this **at entry-creation time, not at Phase 5 cleanup time**: every Phase 2 work-review's proposed actions include not just *additions* (draft prose, new synthesis claims) but also *cuts and downgrades* of existing material that the new work makes redundant or supersedes (see `WORK_REVIEW.md` step g). The growth bias is countered at the point material lands, not retrospectively.

Phase 5 still runs a final whole-document verbosity sanity pass — read the assembled document start to finish, ask *can this same point be made with less text?* paragraph by paragraph, and report the word count before / after with the kinds of cuts made. A pass that finds nothing to cut says so explicitly. But this is a final-check sanity pass, not the primary anti-growth mechanism — the primary mechanism is the per-work cut-and-downgrade actions in Phase 2.

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
