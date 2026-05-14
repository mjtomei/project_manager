# Adversarial Review Methodology

Ported from the Omerta project's by-hand adversarial review loop (originally at `/home/matt/omerta/plans/notes.txt` and `/home/matt/omerta/plans/reviews/`).

Used there to subject a research paper to systematic criticism through multiple cycles, then respond and incorporate. The same shape applies to plans like `pm/plans/plan-regression.md` and to the literature review at `pm/docs/literature-review.md` — anywhere a long written artifact would benefit from a critical pass before it gets implemented or shipped.

## The prompt

Two thematic blocks. Block 1 attacks substance; Block 2 attacks structure and readability.

### Block 1 — substance

Ask the reviewer (a Claude session, fresh, blind to previous review cycles):

- How is this work novel compared to previous work in the field or similar fields?
- What are the weakest contributions, and what makes them so weak?
- What additional simulation / validation / empirical work should be done to make this work more relevant and robust?
- What citations are missing, and how do they factor into the key points and results?
- What logical jumps are there in the paper / plan that make up the weakest links in the chain, and how can they be strengthened?
- What existing work is not receiving the credit it is due, and how is that bias influencing the writing or results?
- What are the methodological flaws in the simulations / experiments / implementation plan, missing parameters or unrealistic assumptions, and how should they be addressed?
- How are the mathematical models / architectural arguments lacking in rigor, and what should be done to improve them in general or in relation to previous work?
- What kind of mathematical proofs or assertions that are otherwise provable in simulation or with empirical data are missing that would strengthen the work or hurt the key points?
- What empirical data contradicts the key points of the work and how are those contradictions addressed?

### Block 2 — structure and readability

- What ideas in the work are not completely clear?
- What sections or sentences seem overly verbose relative to the points they are getting across and value to the work?
- What content is being repeated that shouldn't be and what points aren't being repeated that deserve more emphasis?
- What structural changes could improve readability and the probability of readers continuing to read after they start?
- Do the sections and subsections properly flow into each other in a way that is not too abrupt?
- What hooks or punchy lines would best get your main points across and where should you add them?
- What figures or tables / diagrams / code examples could be added that would be most valuable for demonstrating the core ideas?

## The protocol

1. **Run the reviewer blind**. Each cycle is a fresh Claude session that does not know what previous cycles concluded. Critical — knowing prior findings biases the reviewer toward agreement.

2. **Save the review**. Verbatim, before any response. Filename like `REVIEW_CYCLE_<n>.md`. This is the artifact that gets attacked / responded to next.

3. **Write a response, not edits**. Before changing the source text, write a `REVIEW_RESPONSE_CYCLE_<n>.md` that addresses each finding: agree / disagree / partially-agree, what change (if any) will be made. The response captures the reasoning so future cycles can see why a finding was rejected.

4. **Self-review during response**. Fetch every work the reviewer referenced. Verify the reviewer's claims about prior art (the reviewer can be wrong). Then ask the same questions of yourself — does your own critique surface anything the reviewer missed?

5. **Walk the citation graph**. For the most relevant works the reviewer or the source text cites, follow citations forward (cited-by) and backward (references). Google Scholar is the practical tool. The goal is finding directly-relevant prior work the reviewer didn't surface.

6. **Verify accessibility**. If a paper is paywalled with no open-access version, derivative, or report covering the same ground, remove it from the citations and add it to an appendix of "wanted-but-inaccessible" works with a one-line note on what citing it would have changed.

7. **Increase thoroughness each cycle**. Cycle 2 should produce more findings than Cycle 1 with the response from Cycle 1 already incorporated; Cycle 3 should be the hardest pass. If a cycle produces fewer findings than its predecessor, that's a signal — either the work has genuinely improved or the reviewer is starting to agree with the surrounding context.

8. **Stop when findings get pedantic.** Three cycles was the Omerta paper's natural stopping point. Watch for findings that are nitpicks of phrasing rather than substance — that's the convergence signal.

## How this maps to our project-manager work

Two artifacts in this repo would benefit from this loop:

- `pm/plans/plan-regression.md` — the autonomous regression and bug-fix loop plan. Block 1 maps directly: are the PRs novel? are dependencies right? are the watcher / supervisor architectural arguments sound? are there missing citations from the literature review? Block 2 also applies: does the plan's narrative flow? are sections balanced?
- `pm/docs/literature-review.md` — the literature review itself. The same blind-reviewer pass would catch missing references (especially in the thin areas: watcher architectures, LLM-test fakes) and over-stated claims.

Logs of the Omerta runs are in `pm/docs/adversarial-review/REVIEW_CYCLE_*.md` and `REVIEW_RESPONSE*.md` as worked examples. The reviewer's question set was the same across cycles; what changed was the source text (after each response cycle's edits) and the reviewer's depth of prior-art knowledge (Cycle 3 explicitly began with a literature search of its own).

## Practical execution in this repo

To run a cycle by hand:

1. Open a fresh Claude Code session (not a continuation — fresh) in the project directory.
2. Hand it the prompt from this file plus the artifact to review (e.g., `pm/plans/plan-regression.md`).
3. Tell it to save the review to `pm/docs/adversarial-review/REVIEW_CYCLE_<n>.md`.
4. In a separate session (also fresh, after the cycle is saved), have it produce `REVIEW_RESPONSE_CYCLE_<n>.md`.
5. Apply edits the response calls for; commit.
6. Repeat with the next cycle.

To automate later: a future PR could add `pm review adversarial <artifact>` that wraps the same shape and could plug into the discovery supervisor's cadence. Not in scope for the current plan but worth noting as a follow-up if this becomes routine.

## Worked examples

The five files in this directory are the raw artifacts from the Omerta paper's three review cycles:

- `REVIEW_CYCLE_1.md`, `REVIEW_CYCLE_2.md`, `REVIEW_CYCLE_3.md` — the reviewer's verbatim findings each cycle.
- `REVIEW_RESPONSE.md`, `REVIEW_RESPONSE_CYCLE_3.md` — the author's structured responses (Cycle 2's response was inlined; only Cycle 3's was named explicitly).
- `CITATION_GRAPH_ANALYSIS.md`, `CITATION_VERIFICATION.md` — the citation-graph follow-up work the methodology calls for in step 5–6.

Read these to see what the loop actually produces. The substance is omerta-specific (P2P trust mechanism design) but the *shape* of each document is what to imitate when applying the loop here.
