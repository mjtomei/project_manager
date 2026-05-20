# Citation Audit (methodology)

The per-citation audit step inserted into the augmented adversarial-review cycle (`METHODOLOGY.md` § The augmented cycle). Runs after the review and before the response. Catches over-characterizations, missed alternative perspectives, scope-elisions, and citation-vs-source mismatches at the time they would otherwise land, instead of cycles later.

The audit is **per-citation**, **iterates to convergence within each cycle**, and produces a single doc (`CITATION_AUDIT_CYCLE_N.md`) whose entries carry proposed changes that flow into the response session as additional input alongside the review.

## When the audit runs

- **Cycle 1 of a literature review**: every existing citation in the artifact gets audited.
- **Cycle 2+ of a literature review**: every *new* citation the review proposes adding gets audited. Already-audited citations that are unchanged don't get re-audited.
- **An audit can surface new citations** — work the artifact should also cite (more recent, missed prior art, more authoritative source for an existing claim). Each surfaced citation triggers its own audit *within the same cycle*. The loop converges when an audit pass surfaces no new citations.
- The response session does not start until the audit loop has converged for the cycle.

Historical standalone use of this methodology (the four pre-flow `CITATION_AUDIT_*.md` files on existing lit reviews) is a special case of the in-cycle audit: each was effectively "cycle 1, audit every existing citation, no review preceded it." The mechanics are identical.

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

## Skeptical disposition for audit agents

Every audit agent reads the source paper independently and writes its per-citation entry without deferring to either the reviewer's commentary on the citation (when the citation came from the review's *Missing citations* section) or the prior cycle's treatment of the citation (when re-auditing). The disposition the audit agent's prompt carries:

1. **Assume over-characterization until verified against the source.** Check specifically for elided model-class limitations, domain restrictions, regime caveats, sample-size limits, and alternative perspectives in the source's own discussion section. These are the failure modes prior audits have repeatedly caught.
2. **Surface alternative verdicts the framing makes invisible.** If a different verdict is defensible — e.g., the artifact's (or reviewer's) framing makes the citation look load-bearing when it's actually background — name it and the rationale.
3. **Default low-confidence on ambiguity.** Low-confidence is the right answer when the call is genuinely close. It is *not* a fallback for "I didn't read the source carefully" — it is a signal that human attention is mandatory on this entry.
4. **Propose accept only after independent verification against the source.** Not when the entry "looks reasonable." Reasonable-looking entries are how over-characterization gets through.
5. **Name specific passages when proposing edits or rejection.** A vague "Section 4 overstates" is half-done; point to the exact sentence in the artifact and the exact source claim it misuses.
6. **Calibrate confidence explicitly** (high / medium / low). Agents that mark every entry high-confidence are themselves a failure mode.

The reviewer's *Missing citations* commentary (per `METHODOLOGY.md` Block 1's structured format) is **input context, not a verdict**. The audit may agree, refine, or reject; in any case it verifies independently against the source.

### Failure-mode classes the disposition is built to catch

Four recurring classes of over-characterization that confident-sounding entries slip through under deferential or under-verified audits. The skeptical disposition above is what catches them.

1. **Distinction-collapsing framing.** An entry treats a prior work as "near-twin" with the artifact, eliding a distinction the prior work itself preserves. Pattern: the artifact probes one dimension while the prior work probes a different one, and the source paper explicitly preserves the distinction — but the entry's framing collapses it into sameness, making the artifact's residual contribution look smaller than it actually is.
2. **Inherited-verdict laundering.** An entry takes a prior agent's characterization (e.g., a lit-search summary) at face value without independently reading the source. Symptoms: confident "largely pre-empted by X" claims that vanish when the figures and methodology in X are checked against the artifact's actual scope. The verdict reads as a verification but the verification never happened.
3. **Mechanism misnaming.** An entry uses a plausible-sounding label for a source's mechanism that doesn't match what the source describes. Pattern: the entry says the source did *method-name-A* (which would land cleanly in the artifact's argument) when the source actually does *method-name-B* (which lands differently or not at all). The methodology section of the source explicitly contradicts the entry, but the entry never reads that far.
4. **Scope conflation.** An entry generalizes a method's domain beyond what the source claims — applying a method developed for one setting (e.g., a narrow benchmark) as if it covers a broader setting (e.g., general programs). Pattern: the entry summarizes the headline result correctly but elides the scope condition that determines whether the result transfers.

Each class is "the entry sounds right; the source contradicts when checked." The skepticism rules (above) close the gap by requiring the audit to do the check before proposing accept.

## Consuming the review's missing-citation entries

When the audit step runs at the start of a cycle (per `METHODOLOGY.md` § The augmented cycle, step 2), part of its input is the *Missing citations* section of `REVIEW_CYCLE_N.md` — the structured format the review produces per `METHODOLOGY.md` Block 1.

For each entry the audit loop:

1. **Verifies existence.** Search Scholar / lab pages / OpenReview before treating the citation as not-found (per `CITATION_CRAWL.md` § Recovery from "this citation doesn't exist" — the Choi/Transluce case is the worked example).
2. **Reads the source** against the reviewer's commentary, applying the skeptical disposition above.
3. **Produces the per-citation audit entry** in `CITATION_AUDIT_CYCLE_N.md` per *Protocol* below — verdict either confirms the reviewer's framing, refines it ("yes but for a different claim"), or rejects it ("the reviewer's framing doesn't hold up against the source").

These newly-audited citations enter the loop on the same footing as citations already in the artifact — their verdicts can themselves surface further new citations, and the loop converges when no round surfaces new ones.

## The in-cycle audit loop

Each cycle runs the audit step as a loop until convergence:

1. **Determine the audit set** for this cycle: cycle 1 includes every existing citation in the artifact; cycle ≥ 2 includes every new citation the review proposes adding.
2. **Run audits in parallel** on the audit set (per *Parallelization* above). Each audit produces a per-citation entry; entries' proposed changes carry `provenance: audit-entry`. Entries that surface *new* citations (works the artifact should also cite) list them in a `surfaced-citations:` field.
3. **Gather newly-surfaced citations** from the round's entries.
4. **If newly-surfaced is non-empty**: add them to the audit set and goto step 2.
5. **If newly-surfaced is empty**: the audit loop has converged for this cycle. Write the final `CITATION_AUDIT_CYCLE_N.md` and proceed to the response step (`METHODOLOGY.md` § The augmented cycle).

Use `CITATION_CRAWL.md` as the sub-methodology when an audit needs to surface new citations (Scholar forward/backward walk, key-phrase derivation). The crawl is *internal to the audit step* under the augmented cycle — there's no separate crawl phase.

A practical bound: in real cycles the loop converges in 1–3 rounds for moderate-sized reviews. If it hasn't converged in 5 rounds, the new-citations the audits are surfacing are likely off-topic or the audit set is too broad — escalate to the human.

## What each audit entry produces

The per-citation audit entry's output (per *Protocol step e* above) feeds two consumers:

- **The response session** reads the entry as additional input alongside the review's findings. The response session decides agree/disagree/partial per proposed change and recommends the apply action.
- **The walker UI** surfaces the proposed change with provenance tagged `audit-entry` (vs `reviewer-comment` for review-sourced changes). The walker can pivot from any proposed change to its source entry for context.

The two share format — proposed changes are response-block-shaped (suggested-* / human-* / status / interactions) regardless of which source they came from.

## Why this is necessary

Lit-search agents and reviewer summaries routinely over-characterize prior art in subtle ways — eliding a model-class limitation, a regime caveat, or a domain restriction. These slip past blind reviewers in subsequent cycles because the reviewer is checking against the artifact's text rather than the cited source's actual content.

Failure-mode history in this repo:
- **The "near-twin" framing of Cheng et al. 2026** (Cycle 9–10 user-modeling extension): the doc collapsed an attribute-vs-intent distinction the source preserved; caught only on RC discussion, not by the blind reviewer.
- **The "largely pre-empted" framing of Arora 2023 / Ahmed & Singh 2026** (Cycle 11 precursor): the doc inherited a lit-search agent's verdict without independently reading the figures; the figure-semantics critique was incorrect.
- **The "REINFORCE differential against natural text" framing of Quiet-STaR** (Cycle 11 precursor): mischaracterized the reward (which is sibling-rationale-baselined REINFORCE with m-token lookahead, not a likelihood differential against natural text).

In each case the audit — not the blind reviewer — was the discipline that caught the error.
