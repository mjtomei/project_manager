# Adversarial Review Methodology

Ported from the Omerta project's by-hand adversarial review loop (originally at `/home/matt/omerta/plans/notes.txt` and `/home/matt/omerta/plans/reviews/`).

Used there to subject a research paper to systematic criticism through multiple cycles, then respond and incorporate. The same shape applies to plans like `pm/plans/plan-regression.md` — anywhere a long written artifact would benefit from a critical pass before it gets implemented or shipped.

## The augmented cycle (current canonical model)

The current model augments the original review / response / apply cycle with **two additions**: a per-cycle citation audit step between review and response, and a walker UI for human acceptance of proposed changes before apply. Files per cycle remain `REVIEW_CYCLE_N.md`, `CITATION_AUDIT_CYCLE_N.md` (new), `REVIEW_RESPONSE_CYCLE_N.md` — same shape we already have.

### Cycle steps

1. **Review.** Fresh blind Claude session reads the artifact, produces `REVIEW_CYCLE_N.md` (per *The prompt* below, *The protocol* steps 1–4 and 8–11). The findings include proposed changes — substance edits, citation additions/removals, structural feedback. No edits are applied yet.

2. **Citation audit loop.** *New step.* For each citation that requires audit this cycle (cycle 1: every existing citation; cycle ≥ 2: every new citation the review proposes), run a per-citation audit per `CITATION_USE_AUDIT.md`. An audit can surface *additional* citations that should be added (more recent work, missed prior art, a more authoritative source); each surfaced citation is itself audited. The loop converges *within the cycle* when an audit pass surfaces no new citations. Produces `CITATION_AUDIT_CYCLE_N.md` with one entry per audited citation, each entry's proposed changes tagged with `provenance: audit-entry`. Until this loop converges the next step does not start.

3. **Response.** Fresh blind Claude session reads the review *and* the audit doc together, produces `REVIEW_RESPONSE_CYCLE_N.md` per the protocol below. Proposed changes in the response carry their provenance: `reviewer-comment` for changes flowing from the review's findings, `audit-entry` for changes flowing from the audit's per-citation findings. The response session's job is to verify, decide agree/disagree/partial per finding (narrow-don't-collapse for prior-art findings — see *Principle* below), and recommend the apply action for each proposed change.

4. **Walker UI — optional human acceptance.** *New surface.* The walker reads the response doc's proposed changes and surfaces them for human accept / reject / modify per change. Pre-populated with the response session's recommendations (same pre-fill + bulk-accept + auto-run primitive `plan-litreview-ui.md` documents). Each proposed change's provenance link routes back to the originating review finding or audit entry. In auto-run mode the walker is bypassed and the response session's recommendations apply directly.

5. **Apply.** Accepted changes flow into the artifact. Commit. Onto cycle N+1.

### What changed from the original cycle

The original cycle's three artifacts (review / response / apply) survive unchanged in shape. The two additions slot in cleanly:

- **The audit step** is a new sub-process between review and response. It runs to its own internal convergence each cycle. Its output (the audit doc) is a third input to the response session alongside the review.
- **The walker UI** is a new acceptance surface between response and apply. It is *optional* — auto-run mode skips it and applies the response session's recommendations directly, recording an interaction-log entry per change so the audit trail is preserved.

The skepticism rules from `SUGGESTION_PASS.md` § Suggester disposition apply to the audit agents and to the response session (both are reading prior agents' output adversarially); the citation-graph walk machinery in `CITATION_CRAWL.md` is the sub-methodology audit agents use when an audit needs to surface new citations.

### Standardizations introduced by the augmentation

- **Response-block format** on every proposed change (suggested-* / human-* / status / interactions) so the walker can render and write back consistently.
- **Provenance tagging** on proposed changes (`reviewer-comment` vs `audit-entry`).
- **Citation characterization format** in audit entries — each entry carries the citation header (with working clickable link), tier, doc passage as currently written, what the source actually says (verbatim quote on load-bearing claims), verdict, proposed rewrite. See `CITATION_USE_AUDIT.md` for the full format.

### When the augmentations apply

The augmentations apply when running this cycle to produce or maintain a literature review. They are not required when running the cycle on a plan, a research proposal, or another artifact for which the citation audit is not the load-bearing concern — those configurations can use the original cycle without the audit step.

## The prompt

Two thematic blocks. Block 1 attacks substance; Block 2 attacks structure and readability.

### Block 1 — substance

Ask the reviewer (a Claude session, fresh, blind to previous review cycles):

- How is this work novel compared to previous work in the field or similar fields?
- What are the weakest contributions, and what makes them so weak?
- What additional simulation / validation / empirical work should be done to make this work more relevant and robust?
- What citations are missing, and how do they factor into the key points and results?
- Are existing load-bearing citations characterized faithfully against the source? Where the cited work contains significant alternative perspectives, conditions, or caveats that bear on the argument, are those represented in the artifact?
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

### Block 3 — non-expert accessibility (load-bearing)

**Audience assumption**: someone *evaluating whether to use the tool* without much software-development background. This might be a product manager, a researcher in an adjacent field, a domain expert who needs custom software, a hobbyist who can run commands but doesn't write code daily, or a curious reader trying to understand what the project is. They have ordinary technical literacy — they can read, they can install things, they can follow a tutorial — but they cannot be assumed to know:

- Software-engineering vocabulary as practiced by professionals: branch, merge, PR, diff, refactor, regression, fixture, mock, fuzz, coverage, dependency, container, iteration, scaffolding, harness, hook
- Tools by name: tmux, git, GitHub, podman/docker, pytest, pip, the various Claude products (Claude Code vs Claude API vs Claude.ai)
- The research vocabulary the literature review uses: ACI, RAG, RL, self-play, reward hacking, alignment auditing, verifier-guided generation, episodic memory, actor-critic, agentic workflow
- Implicit context: that we use Claude as the underlying model, what "the loop" refers to, what a "watcher" is in this project, that pm is built on top of Claude Code, what role human review plays

If a passage assumes any of these and doesn't gloss them on first use, the reader will close the tab. They will *not* look up a term to keep reading. They will *not* read three sections to understand the first one.

For the artifact under review, answer concretely:

- **Undefined jargon**: list every term used without an inline gloss that the target reader would have to look up — across all three vocabularies above (software-engineering, tool names, research). For each, propose a one-clause gloss that could be inlined on first use. Be aggressive — terms a working engineer would never flag (like "branch" or "test") still need glossing here if the artifact uses them load-bearingly.
- **Implicit prior-art dependencies**: where does the artifact assume the reader has read a specific paper, knows a specific tool, or has used software like this before? Name those dependencies. The artifact should either (a) summarize the needed context inline, or (b) make clear the section is optional context-building for readers who don't have it.
- **Unmotivated framings**: where does the artifact assume the reader already buys into a perspective? Phrases like "as everyone knows X", "the obvious next step is Y", "of course we want Z." The target reader hasn't agreed to anything yet. Flag these and propose a one-sentence motivation that earns the agreement.
- **Abstract claims without concrete examples**: which load-bearing claims are made in fully abstract terms? The target reader retains information through concrete examples ("you type `pm pr add 'fix the login button'` and pm files a new task, then runs a Claude session that writes the fix") more than through abstract characterizations ("the user files a PR and the implementation watcher drives it through the auto-sequence chain"). Propose example sentences for the worst offenders, *using vocabulary the target reader already has*.
- **Dense paragraphs**: any paragraph longer than ~5 sentences (lower threshold than for an engineer audience) or carrying more than one distinct idea. Suggest where to split.
- **Names dropped without context**: every paper-author-tool-product-method named without a one-line "what it is and why we mention it." E.g., "Reflexion's actor-critic loop" requires explaining what Reflexion is, what an actor-critic loop is, and why the analogy helps the reader understand pm. Without all three, the name-drop is noise.
- **Insider-only quips, in-jokes, or hedged language**: phrases that signal in-group membership rather than communicate substance ("it's complicated", "the usual caveats apply", "modulo the obvious limitations", "you know how it goes"). Replace with the actual substance or cut.
- **Quantitative claims without scale anchors**: numbers given without telling the reader whether they're good or bad and *what they are measuring* ("42-50% sensitivity" — sensitivity of what to what? is that high or low? compared to what?). Propose anchor comparisons in plain English.
- **Acronym and abbreviation creep**: every acronym must be spelled out on first use, even ones that feel obvious. "PR" (pull request), "QA" (quality assurance / testing), "CI" (continuous integration), "TUI" (terminal user interface), "CLI" (command-line interface), "API" (application programming interface). For tool-internal acronyms invented by this project (`pm`, watchers, etc.), explain what they refer to before using them load-bearingly.
- **"Why should I care?" check**: read each section opening and ask whether the target reader knows, by the end of the first paragraph, *what they get from reading this section*. If the section opens with a paper citation or a technical-sounding claim, it has probably failed the check. Propose an opening sentence that names a concrete benefit to the reader.

**Important**: for every accessibility finding, *propose the specific simplification* rather than just flagging the problem. A finding that says "Section 4 uses jargon" is useless; a finding that says "Section 4 line 88 uses 'actor-critic loop' — the target reader doesn't know what this is, what an actor is in this context, or what a critic is; replace with 'a writer-and-checker pair, where the writer produces a candidate answer and the checker decides whether to accept it; rejected candidates get rewritten'" is useful. The point of this block is to make the artifact actually usable by its stated audience, not to demonstrate the reviewer's vocabulary.

**Test the rewrite**: for the three or four longest accessibility findings, write the replacement sentence(s) and read them back as if you were the target reader. If a glossed sentence introduces *new* jargon that wasn't in the original, it has failed — try again.

This block is **load-bearing** because the artifact's stated goal includes being readable by people considering using the tool. A review that catches every citation error but misses the accessibility failures has missed the artifact's core obligation. *Catching jargon a working engineer would have used without thinking is the whole job here.*

### Block 4 — writing quality and prose craft

Block 2 covers macro flow (section-to-section transitions, structural moves, hooks, paragraph-level repetition). Block 3 covers accessibility (jargon, glosses, scale anchors). Block 4 covers what's between them: the prose itself at the paragraph, sentence, and word level.

This block is for what a working copy-editor would flag — issues that don't affect what the text *means* but that affect how it *reads*. A sentence that is technically correct, accessible to the audience, and structurally in the right place can still be ugly, ambiguous, awkward, monotonous, or imprecise. Block 4 catches those.

For the artifact under review, answer concretely:

- **Paragraph-level cohesion**: does each paragraph carry one idea? Find paragraphs that string together two or three distinct ideas without a clear connecting argument — propose where to split. Find paragraphs whose topic sentence doesn't match what the rest of the paragraph actually does — propose a rewritten topic sentence or a restructure.
- **Paragraph-to-paragraph flow**: does paragraph N's last sentence set up paragraph N+1's first sentence? Look for adjacent paragraphs where the topic shifts without a transition. Propose the bridging sentence or clause.
- **Sentence-to-sentence transitions inside paragraphs**: look for paragraphs where every sentence starts with the same kind of grammatical structure ("The plan does X. The plan also does Y. The plan further does Z."), or where sentences sit side-by-side without logical connectives (because / so / however / instead). Propose the rewritten transitions.
- **Voice and tone consistency**: does the document maintain one register? Find passages that slip between formal-academic ("we hypothesize that"), casual-explanatory ("you'd close the tab here"), and corporate-flat ("this represents a significant contribution"). Propose the consistent register and rewrite the outliers.
- **Sentence rhythm and variety**: find runs of three-plus same-length, same-structure sentences. Propose a varied alternative. Also flag the opposite — a string of overly-clever varied-structure sentences that obscure the content instead of conveying it.
- **Word-choice precision**: words that are *roughly right* vs. words that are *exactly right*. Find sentences using vague verbs ("involves," "deals with," "is related to," "looks at") where a specific verb would say more. Find adjectives that pad rather than discriminate ("substantial," "significant," "important," "key"). Propose precise replacements.
- **Deadwood and bloat**: find phrases that can be cut without losing meaning ("it should be noted that," "in many cases," "as a matter of fact," "the fact that," double-negatives that resolve to positives, qualifiers stacking on qualifiers). Propose the cut.
- **Awkward constructions**: passive voice used reflexively rather than for effect, nominalizations that should be verbs ("the establishment of" → "establishing"), buried verbs and subjects, run-on sentences with three or more independent clauses connected by "and."
- **Hedging vs. confidence**: catch every hedge ("seems to," "may be," "might possibly," "tends to," "appears to," "in some sense") and judge whether it earns its place. A hedge on a real uncertainty is right; a hedge on a confident claim is a stylistic tic to cut. Propose the cuts.
- **Heavy modifiers and intensifiers**: "very," "really," "quite," "rather," "fairly," "somewhat" — most can be cut. Propose the cuts.
- **Emphasis restraint**: italicizing, bolding, all-caps, dashes-for-drama — used sparingly these emphasize; used densely they cancel each other. Count the emphasis density per page and propose what to leave un-emphasized.
- **Clichés and corporate-speak**: phrases that survive on familiarity rather than precision ("leverage," "stakeholders," "best-in-class," "robust," "comprehensive," "holistic," "going forward"). Propose direct replacements.
- **Sentence-internal logical structure**: in long sentences, does the subject control the verb? Is the most important clause the main clause? Find sentences where the load-bearing claim is buried in a subordinate clause and the main clause is throwaway. Propose the inversion.

**Important**: for every Block 4 finding, propose the specific rewrite — show the before-and-after sentence or paragraph. A finding that says "this paragraph is awkward" is useless; a finding that says "the third sentence of paragraph two reads 'The plan does X, which represents a significant departure from the existing approach' — replace with 'This breaks with the existing approach in X'" is useful. Block 4 is the most explicit-rewrite-heavy block; the reviewer's job is to do the rewriting work, not flag the rough edge.

Block 4 is **not** load-bearing the way Block 3 is — readers can accept ugly prose if the substance is right. But it's the difference between a document that's *read* and a document that's *referred to*. A lit review with crisp prose is the one people actually finish.

## The protocol

1. **Run the reviewer blind**. Each cycle is a fresh Claude session that does not know what previous cycles concluded. Critical — knowing prior findings biases the reviewer toward agreement.

2. **Save the review**. Verbatim, before any response. Filename like `REVIEW_CYCLE_<n>.md`. This is the artifact that gets attacked / responded to next.

3. **Write a response, not edits**. Before changing the source text, write a `REVIEW_RESPONSE_CYCLE_<n>.md` that addresses each finding: agree / disagree / partially-agree, what change (if any) will be made. The response captures the reasoning so future cycles can see why a finding was rejected.

4. **Self-review during response**. Fetch every work the reviewer referenced. Verify the reviewer's claims about prior art (the reviewer can be wrong). Then ask the same questions of yourself — does your own critique surface anything the reviewer missed?

5. **Walk the citation graph — explicitly, on Google Scholar, with named seeds.** The biggest recurring miss in our loops has been new prior art that exists but the reviewer didn't find. The remedy is procedural, not a matter of trying harder:

   a. **List the seeds explicitly before searching.** Pick the 5–8 most-cited or most-load-bearing references the artifact already names. Write them down. The seed list is the audit trail — if a Cycle 3 reviewer finds a key paper the artifact missed, the previous reviewer's seed list shows which seed should have led there.

   b. **For each seed, walk both directions on Google Scholar.** Forward: click "Cited by" on Scholar's seed entry and read the most-recent 20–30 citing papers. Backward: scan the seed's own References for prior art the artifact doesn't yet cite. Time-budget per seed: 5–10 minutes. Total time-budget: 30–60 minutes for the walk.

   c. **Use Scholar's date filter aggressively.** Sort by date, restrict to the last 12 months, and look specifically for very-recent work (last 30 days especially) — that's where missed prior art accumulates because the artifact's earlier draft predates the publication. The most damaging misses in our loops have all been from the last 6 months.

   d. **Search beyond arXiv.** Key methodology papers in this space appear at transformer-circuits.pub (Anthropic), alignment.anthropic.com (Anthropic Alignment Science), OpenReview, ACL Anthology, transluce.org, and various lab blogs. Searching "arxiv:<topic>" alone misses these. Search the topic plain, then check the lab pages of the relevant research groups (Anthropic, Transluce, DeepMind interpretability, AISI) directly.

   e. **For citations the reviewer flagged as unverifiable or hallucinated**: the next cycle's reviewer must explicitly search Google Scholar, the lab's own page, and OpenReview for the named work before treating it as not-found. Cycle 1's reviewer flagged "Choi et al. 2025" and the response substituted a different paper — but Choi/Transluce 2025 was real, just not on arXiv. Default to "search more places" before "doesn't exist."

   f. **Specific search recipes per topic cluster** (concrete, named tactics):
      - *Activation-to-language readout / probing methodology*: search transformer-circuits.pub, alignment.anthropic.com, transluce.org, and OpenReview for "activation verbalizer," "activation oracle," "patchscope," "latent decoder," plus a Google Scholar "cited by" walk on Patchscopes (Ghandeharioun 2024).
      - *Autonomous coding agents / benchmarks*: search swebench.com, OpenHands' GitHub, and Scholar "cited by" on SWE-Bench (Jimenez 2024).
      - *LLM agent integrity / cheating detection*: search nist.gov/caisi, alignment.anthropic.com, and Scholar "cited by" on ImpossibleBench (Zhong 2025).
      - *Social-psychology framework for person perception*: search Scholar "cited by" on Fiske/Cuddy SCM (2002) and Goodwin 2014 — both have substantial follow-up literature including the dispute over how many dimensions structure person perception.

   g. **Report the walk's coverage explicitly in the review.** Include a "Citation graph walk" section listing: which seeds were searched, the date range covered, the count of new citing/cited papers found per seed, and the additions proposed. If the walk found nothing new, say so — that's a positive convergence signal.

6. **Citation-use audit (light, per-cycle) → see `CITATION_USE_AUDIT.md` for the thorough version.** Within each response cycle do a *light* check of any newly-added or reviewer-touched citations against their abstracts. The dedicated full-text audit — full papers read, standalone audit doc with per-citation proposed rewrites — happens between cycles after a large citation expansion, and as the final pass once iterative review converges. It lives in its own methodology file (`CITATION_USE_AUDIT.md`) and is invoked from the top-level flow (`LITERATURE_REVIEW_FLOW.md`, Phase 3). The two are complementary to the citation-graph walk (step 5): the walk finds *what should be cited*; the audit checks *that what is cited is used faithfully*.

7. **Verify accessibility**. If a paper is paywalled with no open-access version, derivative, or report covering the same ground, remove it from the citations and add it to an appendix of "wanted-but-inaccessible" works with a one-line note on what citing it would have changed.

8. **Increase thoroughness each cycle**. Cycle 2 should produce more findings than Cycle 1 with the response from Cycle 1 already incorporated; Cycle 3 should be the hardest pass. If a cycle produces fewer findings than its predecessor, that's a signal — either the work has genuinely improved or the reviewer is starting to agree with the surrounding context.

9. **Stop when findings get pedantic.** Three cycles was the Omerta paper's natural stopping point. Watch for findings that are nitpicks of phrasing rather than substance — that's the convergence signal.

10. **Once length is flagged, the response cycle must net-cut.** The loop has a structural bias toward growth: each cycle surfaces new prior art and new findings, and the natural response is to *add* — a citation, a rebuttal paragraph, a clarifying gloss. Across the living-artifacts review, every cycle flagged the document as too long and every response added material anyway; it grew from ~13,000 to ~16,000 words while its load-bearing accessibility obligation got worse. The remedy is a hard rule: once any reviewer flags length, that cycle's response must produce a **net word reduction**, and the apply pass must count words before and after to confirm it. New citations go in tersely (one sentence each); every addition is paired with a larger cut; dense survey material moves to an appendix rather than sitting in the body. If the apply pass nets positive or flat, it has failed and must be redone. A document that converges on substance but bloats on length has not converged.

   **Cut against the whole narrative, not just the recent additions.** The net-cut is not satisfied by trimming whatever the latest cycle added. Every cut pass is a fresh whole-document hunt for text that is unnecessary or verbose *relative to the point it makes* — regardless of which cycle wrote it. If a paragraph from the original draft makes a point that a sentence could carry, cut it down; if a point is made twice in different sections, keep the stronger statement and delete the other; if a sentence survives only on familiarity, cut it. The standing question on every pass is: *can this same point be made with less text?* If yes, do it. Length budget is spent on points, not on prose that surrounds them.

11. **Run a whole-document verbosity pass every cycle.** Independently of whether a reviewer flagged length, every cycle includes one pass over the *entire* artifact whose only job is to find text that is verbose relative to the point it makes and cut it tighter. This is a standing step, not a contingency: it runs even on cycles where no length finding was raised, because verbosity accumulates everywhere, not only in new material. The pass reads the document start to finish and, for every paragraph and sentence, asks *can this same point be made with less text?* — applying it to original-draft prose as readily as to recent additions. Record the pass in the response file: the word count before and after, and the kinds of cuts made (redundant restatement, hedge stacking, deadwood, a paragraph that a sentence carries). A cycle whose verbosity pass found nothing to cut should say so explicitly — like the citation walk finding nothing, that is a convergence signal.

## Principle: narrow the contribution; don't collapse it

When a reviewer surfaces closer prior art — a paper that does some of what the artifact claims is novel — there are two failure modes the response cycle has to avoid:

**Failure mode A** — *capitulate*. Accept the reviewer's framing wholesale, agree the prior art "did the same thing," cut the contribution claim to zero. This was the move that almost happened with LatentQA in Cycle 1 of the user-model lit review (the response substituted LatentQA for the missing Choi/Transluce; the substitute paper turned out to do something materially different from what we thought). It's also the move that almost happened when Cycle 3 surfaced Choi/Transluce and Cycle 4 surfaced Goodwin et al. — each time the temptation was to collapse the novelty story rather than re-state it precisely.

**Failure mode B** — *hold the line too hard*. Insist the artifact is doing something genuinely new even after the prior art makes that hard to defend, with the result that the contribution claim reads as special-pleading.

**The correct move is to narrow, not collapse.** When prior art is surfaced:

1. **List what the prior art actually does**, sourced from its abstract (verified — see the next section). Be precise about variable, methodology, dependent measure, scope, and experimental setup.
2. **List what the artifact under review does**, in the same terms.
3. **Compute the intersection**: what does the prior art preempt? That's what the contribution claim has to give up.
4. **Compute the artifact's residual contribution**: what does the artifact do that the prior art doesn't? List it as specifically as the artifact actually delivers — not what the artifact's authors aspire to but what the artifact's described methodology actually produces. The residual is the new, narrower contribution claim.
5. **Update the artifact's contribution statement to the residual.** Replace the old framing wholesale; do not add hedges to the old framing.

The result, done right, is a contribution claim that is smaller than the old one but stronger because it's defended against the prior art on point-by-point grounds. The Cycles 3-and-walk handling of Choi/Transluce → Deas & McKeown in the user-model lit review is the worked example: the original "first to probe user-modeling representations" claim shrank to "extends Choi's user-attribute decoding to the peer-ness meta-dimensional structure" (Cycle 3), then to "extends the Deas/McKeown SCM-linear-probe lineage with contrast-pair extraction, task-performance DV, Phase 3 causal mediation, and Phase 4 closed-model transfer" (walk). At each step the contribution narrowed but did not collapse, and each narrower version was more defensible than the broader one it replaced.

The hardest part of this move is the verification step (next section). It's tempting to take the reviewer's characterization of the prior art at face value, because the reviewer sounds confident. Don't. Fetch the prior-art paper's abstract directly. Confirm it does what the reviewer says it does, on the variables and DV the reviewer says it does. The LatentQA-substitution and the walker-over-characterized-AuditBench moments both happened because someone trusted a confident-sounding summary instead of the source.

### Procedural rule

When a response cycle accepts a prior-art finding, the response file must include:

- A "What [prior art] actually does" subsection sourced from the abstract (with a verbatim quote from the abstract where load-bearing claims are made).
- A "What the artifact does that [prior art] doesn't" subsection enumerating the residual contributions.
- The replacement contribution statement, written out, that goes into the artifact's edit.

A response file that just says "accept the finding, the prior art preempts our novelty claim" without producing the residual is rejected. So is a response file that says "disagree, our work is different" without the point-by-point comparison.

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
