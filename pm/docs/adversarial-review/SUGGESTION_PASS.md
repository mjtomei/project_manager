# Suggestion Pass (methodology)

The walker UI's response block (see `plan-litreview-ui.md` § Interaction model) is pre-filled with a *suggested response* for each decision point. The suggestion is written by a **separate sub-agent** — a "suggester pass" — that runs *after* the entry-writing agent has produced the entry. The two agents are independent, mirroring the adversarial-review pattern that the rest of this directory uses: the entry-writing agent produces material; a separate reviewer agent looks at it and proposes how the human should respond.

## Why a separate sub-agent

The entry-writing agent has reasoning context tuned to producing the entry — it has read the source paper, identified load-bearing content, drafted prose. Asking the same agent to also produce the *suggested human response* risks:

- **Self-confirmation bias.** The agent that wrote the entry has invested in that entry being correct; its suggestion will lean toward "accept what I wrote." A separate agent reads the entry fresh, with no investment.
- **Missed adversarial reading.** The entry-writing agent isn't looking for problems with the entry; it's looking for problems with the source paper. The suggester's job is to look for problems with the entry.
- **Compressed reasoning.** Suggestion-writing is a distinct reasoning task — *what would a careful human verdict be on this entry?* — that gets shortchanged when bolted onto the entry-writing task as a postscript.

The suggester pass is the same adversarial-independence pattern the four existing citation audits already use. It applies the pattern to every walker decision, not just to retrospective audits.

## What the suggester reads

- The entry itself (the scan summary, the work-review entry, the crawl candidate, the synthesis claim, or the proposed prose edit).
- The source the entry is about — the paper's abstract or, for Tier-1 work-reviews, the same depth of read as the entry-writing agent.
- The prior accepted synthesis claims for the artifact (so the suggester can spot when an entry contradicts a prior decision the entry-writing agent may have overlooked).
- The artifact's current state (the lit review draft, plan, or topic seed) so the suggester can judge relevance and load-bearing claims against the actual argument.

## What the suggester produces

For each decision field in the entry's response block:

- **suggested-verdict** — the verdict a careful human would land on, given the entry and the source. Same enum as the human will use.
- **suggested-rationale** — one to three sentences explaining the suggestion's reasoning. This is what the human reads first; if it's compelling and matches the human's own read, they accept-as-suggested. If it surfaces a tension the human disagrees with, they edit.
- **suggested-commentary** (optional) — additional context the human might want to know before deciding (e.g., "this entry contradicts the framing in `[[synthesis-claim-X]]`; verify before accepting").
- **suggester-confidence** — `high` / `medium` / `low`. Low-confidence flags entries where the suggester thinks the call is genuinely ambiguous and human attention is mandatory. The walker filters can surface low-confidence entries first.

## When the suggester runs

Triggered automatically after the entry-writing pass completes. In the session-integration flow (see `plan-litreview-ui.md` § Ready-task execution), each completed entry-writing task enqueues a follow-up *suggester pass* task into the ready-task queue. The walker does not show an entry until its suggester pass has also completed — otherwise the response block is empty and the human has nothing to react to, defeating the pre-fill primitive.

For bulk iterations (e.g., scanning 30 candidates in iteration 1), entry-writing and suggester passes pipeline: while batch N's entries are being suggested-on, batch N+1's entries are being written.

## Audit trail

Each suggestion in the response block carries a pointer to the suggester pass's full reasoning artifact — typically a single-file output named like `SUGGESTIONS_<artifact>_<phase>_iter<N>.md`. The walker shows the one-to-three-sentence rationale by default; clicking through opens the suggester's full analysis (the same shape as an adversarial-review doc). This means the human can audit the suggester's reasoning the same way they audit any other pass — separately, with the suggester's full prose in front of them.

## Suggester for proposed edits

Proposed edits to the lit review prose (from work-review draft prose, synthesis claims that imply prose changes, or audit-mode rewrites) go through the same suggester pattern. A separate sub-agent reads the proposed-edit (before / after / provenance) and produces the suggested human verdict (`accept` / `modify` / `reject`) plus rationale. The proposed-edits walker (see `plan-litreview-ui.md`) consumes that suggestion the same way the other walkers consume theirs.

## Where the suggester *doesn't* run

The suggester pass does not run on entries the human has already acted on. Once `status` is `accepted-as-suggested`, `edited`, or `skipped`, the suggestion is fixed (the suggested-* fields stay in the response block as audit history; the human-* fields are canonical). A *regenerate suggestion* button in the walker (later optional PR) can re-trigger the suggester on demand, useful after the human has edited prior synthesis claims that the suggester's reasoning was anchored to.

## Companion files

- `plan-litreview-ui.md` — the walker UI that consumes suggestions.
- `WORK_REVIEW.md` — Phase 2 entry-writing methodology; suggester runs after each work-review.
- `INITIAL_SCAN.md` — Phase 1 entry-writing methodology; suggester runs after each scan entry.
- `CITATION_CRAWL.md` — Phase 3 candidate surfacing; suggester runs to produce suggested triage verdicts.
- `SYNTHESIS.md` — synthesis claim production; suggester runs to produce suggested resolutions.
- `CITATION_USE_AUDIT.md` — audit-mode rewrite proposals; suggester runs to produce suggested verdicts on each.
