# Review Response — Cycle 5 — Literature Review: Living Artifacts

Responding to `REVIEW_CYCLE_5_LIVING_ARTIFACTS.md`. Date: 2026-05-15.
Artifact: `pm/docs/literature-review-living-artifacts.md` (~11,700 words).

Methodology compliance: this is a length-flagged cycle (every prior cycle flagged
length; step 9 applies). The apply pass **must net negative.** Target: net
reduction of ≥520 words. This response specifies every cut explicitly with a
running net-words tally. Whole-document verbosity pass run independently of the
reviewer's list (step 10).

---

## Part 1 — Prior-art verification (verify-before-write)

All three flagged arXiv IDs resolve to real papers. Abstracts fetched and quoted
verbatim below. None is unverifiable; none is hallucinated. But two of the three
are **over-stated by the reviewer**, and the verification narrows them.

### MEMOREPAIR — arXiv:2605.07242 — VERIFIED, reviewer accurate

Verbatim abstract (key clauses): *"Agentic memory evolves across tasks into
durable derived artifacts: summaries, cached outputs, embeddings, learned skills,
and executable tool procedures. When a source artifact is deleted, corrected, or
invalidated ... descendants derived from that source can remain visible and steer
future actions with stale support. We formalize this failure mode as the cascade
update problem ... A repair event induces a controlled transition from invalidated
descendant state to validated successor state ... republication is restricted to
validated predecessor-closed successors ... the induced publication problem
reduces to maximum-weight predecessor closure and can be solved exactly by a
single s-t min-cut. Experiments on ToolBench and MemoryArena show that ...
MemoRepair reduces invalidated-memory exposure from 69.8-94.3% ... to 0%."*

**What it actually does:** formalizes the stale-derived-artifact problem ("cascade
update problem"), models memory as a provenance graph, and gives an exact
*centralized* repair algorithm (single s-t min-cut). The reviewer's S1
characterization is accurate — this is the closest published prior art to the
plan's self-maintenance mechanism, and it is genuinely uncited.

**Narrow, don't collapse.** MEMOREPAIR preempts: that *naming and formalizing*
"derived artifacts go stale when their source changes" is unprecedented — it is
not. Residual: MEMOREPAIR's repair is a deterministic graph algorithm with a
single repair event recomputing a closure (the central adjudicator the plan
relocates away from); it has no negotiation, no wants, no task lifecycle, and its
artifacts are passive memory blocks. The plan's self-maintenance is the
decentralized, judgment-resolved counterpart — no provenance min-cut, but no
central repair event either.

**Corrected-scope citation sentence (one sentence, ADD to B§5 ScienceClaw
paragraph):** *"MEMOREPAIR (arXiv:2605.07242, 2026) formalizes the
stale-derived-artifact problem as the 'cascade update problem' and solves it
exactly with a centralized provenance min-cut; the plan's self-maintenance is the
decentralized, judgment-resolved counterpart — the repairing task negotiates as a
peer rather than recomputing a closure."*

Note: the reviewer's S1 prose contains a typo — it cites "2606.07242" in the
proposed sentence while the heading says "2605.07242." The correct ID is
**2605.07242** (verified). Also: the reviewer's claim that MEMOREPAIR is "closer
than ScienceClaw" is half-right — closer on the *stale-cascade* sub-problem, not
on the negotiating-peer architecture. The exec-summary "ScienceClaw ... closest
published thing to the plan's self-maintenance" line is softened to "among the
closest" (see edit 4).

### CORAL — arXiv:2604.01658 — VERIFIED, reviewer slightly OVER-stated

Verbatim abstract (key clauses): *"Existing methods still rely heavily on fixed
heuristics and hard-coded exploration rules, which limit the autonomy of LLM
agents. We present CORAL, the first framework for autonomous multi-agent evolution
on open-ended problems. CORAL replaces rigid control with long-running agents that
explore, reflect, and collaborate through shared persistent memory, asynchronous
multi-agent execution, and heartbeat-based interventions ... On Anthropic's kernel
engineering task, four co-evolving agents improve the best known score ..."*

**What it actually does vs. the reviewer's claim:** the reviewer's S3 quote ("agents
that control retrieval, proposal, evaluation, and knowledge accumulation") does not
appear in the verified abstract — that is a paraphrase, likely from the body, and
should not be quoted as abstract text. The verified abstract is narrower: CORAL
replaces *fixed heuristics and hard-coded exploration rules* with autonomous
long-running agents that explore/reflect/collaborate. The reviewer's substantive
point survives: CORAL puts agent autonomy *inside* the evolutionary loop. But it
does **not** preempt B§6's sliver — the abstract is explicit that CORAL's agents
operate the loop's machinery; selection of candidates is still loop-driven.

**Narrow, don't collapse.** CORAL preempts: that "autonomous agents operating an
evolutionary loop" is unbuilt — it is now built. Residual: B§6's *negotiated
internal selection* — candidates evaluating their own fitness and negotiating
their own survival — is untouched; CORAL's autonomy is in the operators, not in the
candidates selecting themselves.

**Corrected-scope citation sentence (one sentence, ADD to B§6):** *"CORAL
(arXiv:2604.01658, 2026) builds autonomous agents that run an evolutionary loop's
operators, which narrows the gap but not the sliver: the unclaimed element is
selection emerging from the candidates themselves, not autonomous agents operating
the loop's machinery."*

### Consensus Trap — arXiv:2604.17139 — VERIFIED, reviewer OVER-stated

Verbatim abstract (key clauses): *"Multi-agent large language model (LLM)
architectures increasingly rely on response-level aggregation, such as Majority
Voting (MAJ) ... agents are highly susceptible to stealthy contextual corruption,
such as targeted prompt injections. We reveal a critical structural vulnerability
... response-level aggregation collapses when corrupted agents form a local
majority ... we propose the Token-Level Round-Robin (RR) Collaboration ... while
MAJ collapses when corrupted agents reach a majority, RR maintains robust accuracy
well beyond this critical threshold."*

**What it actually does vs. the reviewer's claim:** the reviewer (S2) cites this for
"sycophantic false consensus" and "oscillation between facts and lies." Neither
phrase appears in the verified abstract. The Consensus Trap paper is about
**adversarial prompt injection collapsing majority-vote aggregation** — an
adversarial-corruption result, not a sycophancy-or-oscillation result. The
reviewer has conflated it with a different strand of multi-agent-debate-stability
literature. **Partially reject S2's citation:** the Consensus Trap *can* be cited
for "false consensus under a corrupted majority," but NOT for sycophancy or
fact/lie oscillation. The plan's convergence risk in B§5 is about *honest*
non-termination, not adversarial attack — so Consensus Trap is only loosely on
point. Cite it tersely as one named failure mode; do not let it carry the whole
convergence-risk claim, and do not attribute claims to it that its abstract does
not support.

**Corrected-scope citation sentence (one sentence, REWRITE B§5 convergence
paragraph):** *"Recent multi-agent work names concrete failure modes — e.g. the
'Consensus Trap' (arXiv:2604.17139, 2026) shows majority-vote aggregation
collapsing under a corrupted local majority; the plan's timeout-into-dropped rule
is one mitigation among several and is untested here."*

---

## Part 2 — Non-prior-art substantive findings

### S4 — CodeCRDT 5–10% figure over-leaned-on — ACCEPT (this is a CUT)

Agreed. The figure appears four times (Introduction-adjacent reasoning is actually
in the conclusion (b/c) cluster; plus conclusion (c), B§2 CodeCRDT bullet, and the
coverage-gaps list). The argument survives on the *existence* of a non-zero
residue, not on the specific percentage. **Keep the figure once** — in the B§2
CodeCRDT bullet, where the 600-trial provenance and the prose-transfer caveat
belong together. Strip the number from conclusion (c) and from conclusion (b);
keep a bare reference in the coverage-gaps list (no restated caveat). See edits
9, 10, 17.

### S5 — Instance 3 "tuple space" overreach — ACCEPT (REWRITE, net ~0)

Agreed. B§1 is careful ("the task queue inside one artifact ... a tuple space
scoped to one document"); Instance 3 elevates this to the whole substrate being a
tuple space, which is false — the substrate is a federation of per-artifact queues
plus cross-artifact negotiation. Narrow Instance 3's sentence to match B§1 rather
than argue the federation claim (arguing it would add words; this is a net-cut
cycle). See edit 6.

### S6 — MMP "production" hedge stated three times — ACCEPT (this is a CUT)

Agreed. The hedge appears in the exec summary, the conclusion's MMP section, and
the references entry. **Keep it once, in the references entry** (the natural home
for a provenance caveat). The conclusion's MMP section says "MMP runs that" as
fact while hedging elsewhere — fix the register: the conclusion should say "MMP
specifies that" (preprint claim, not verified deployment). The exec summary's MMP
bullet drops the hedge entirely and just states the different-problem verdict. See
edits 3, 14, 15.

---

## Part 3 — Accessibility findings

### A1 — gloss-stacking (80-word sentences, three nested glosses) — ACCEPT (REWRITE/CUT)

This is the load-bearing Block-3 finding and it is correct. Two offenders:

1. **Conclusion opening sentence** (~80 words, three parenthetical glosses, two
   em-dash clauses, a citation). The conclusion's bullet list (d) *already* states
   the three properties cleanly. The one-sentence version is redundant *and*
   inaccessible. **CUT it**; let the (d) bullets carry the contribution. See
   edit 11.

2. **Introduction "What surrounds the plan" closing sentence** — same shape,
   nested glosses for "relational," "first-class," "superposition." **REWRITE** as
   four short sentences, zero parentheticals (reviewer's proposed rewrite is
   sound and adds no jargon):
   > "The plan builds something new on top of the project's files. The file keeps
   > its own half-decided changes. It records how it connects to other files. And
   > it uses an AI to settle disagreements between competing changes — work that,
   > until recently, only a person could do."
   See edit 5.

### A2 — "first-class" glossed three times — ACCEPT (folds into A1)

Glossing the same term three times means none is trusted. After edits 5 and 11
remove two of the three glosses, only the Introduction first-use gloss survives —
which is the correct outcome. No separate edit; A2 is discharged by A1's cuts.

### A3 — "DAG" unglossed — ACCEPT (small ADD, ~6 words)

First load-bearing use is B§4 ("over an adaptive DAG"). Add an inline gloss "— a
dependency graph with no cycles —" on that first use. "min-cut" in the new
MEMOREPAIR sentence: the sentence already reads "provenance min-cut" in a context
that conveys it is an algorithm; no extra gloss needed (keeps the net-cut). See
edit 8.

### A4 / A5 — "superposition" / "stigmergy" — PARTIAL ACCEPT, defer

A4 (superposition): valid but low-yield; demoting it to a parenthetical is a
phrasing change that nets ~0 words. Defer to a phrasing-only Cycle 6. A5
(stigmergy): reviewer themselves rates it lowest-priority and appendix-acceptable.
Defer. Neither blocks convergence.

### Diagram decision — ADD a compact ASCII data-structure diagram

The reviewer (St4) flags eleven thousand words describing a data structure with no
figure, and notes a missing diagram is a *standing* unaddressed Block-2 finding
that should be escalated, not re-deferred. **Accepted.** A diagram earns its
budget for the non-developer reader. Add a compact ASCII figure of the artifact
data structure to the conclusion's (d) section — the five labelled compartments
the task asks for. It costs ~70 words but replaces prose the (d) bullets currently
spend describing the structure abstractly. Net cost after the offsetting prose
trim: ~+45 words. The diagram (edit 12):

```
   LIVING ARTIFACT
   +---------------------------------------------------+
   | DOCUMENT BODY        the human-readable rendering  |
   |---------------------------------------------------|
   | LIVE TASK QUEUE      in-flight tasks, unsettled    |
   |                      proposals held side-by-side   |
   |---------------------------------------------------|
   | NEGOTIATION HISTORY  how competing changes were    |
   |                      argued out; cross-artifact    |
   |                      references                    |
   |---------------------------------------------------|
   | SELF-MAINTENANCE     checks the artifact spawns    |
   | SCHEDULE             from its own "wants"          |
   |---------------------------------------------------|
   | REJECTION LOG        proposals dropped, and why    |
   +---------------------------------------------------+
```

---

## Part 4 — Structure findings

- **St1 (triple-stated contribution)** — ACCEPT, handled by edits 2, 11 (CUT).
- **St2 (calibration overlap between "Prior art in brief" and "Read on the
  framing")** — ACCEPT. Make "Prior art in brief" purely descriptive; let "Read
  on the framing" carry calibration. CUT the calibration clauses from the brief.
  See edit 7.
- **St3 (B§8 stub)** — ACCEPT. B§8 is a 4-sentence pointer. Fold its one new
  sentence (InfiAgent / "Everything is Context" as the frontier) into the "Prior
  art in brief" Claude Code bullet; delete B§8. See edit 16.

## Part 5 — Prose-craft findings (P1–P5)

ACCEPT as a bundled trim, executed in edit 13: convert ~half the em-dashes in the
flagged sentences (P1); cut "load-bearing" from 5 uses to 2 (P2); cut "genuine"
from 4+ uses to 1 (P5); cut the unearned hedges "might want to" and "usually"
(P4). P3 ("the plan should" ×12) — accept partially: vary three instances, no
word change. Bundled estimate: ~60 words.

---

## Part 6 — Verbosity cuts and running net-words tally

Whole-document pass run start to finish (step 10). The reviewer's step-10 list is
the spine; the items marked **[whole-doc pass]** are additional, not on the
reviewer's list.

Running tally below. ADD = words added; CUT = words removed.

| # | Type | Edit | Δ words | Net so far |
|---|------|------|---------|-----------|
| 1 | ADD | B§5: MEMOREPAIR sentence (S1) | +40 | +40 |
| 2 | ADD | B§6: CORAL sentence (S3) | +38 | +78 |
| 3 | REWRITE | B§5: Consensus Trap sentence (S2), replaces vague "multi-agent-debate work" clause | +5 | +83 |
| 4 | REWRITE | Exec summary: "closest published thing" → "among the closest"; drop MMP hedge from exec bullet | −35 | +48 |
| 5 | REWRITE | Intro "What surrounds the plan" closing sentence → four short sentences, de-stacked (A1) | −70 | −22 |
| 6 | REWRITE | Instance 3: narrow "the artifact substrate ... is a tuple space" to "each artifact's task queue is a tuple space scoped to that document" (S5) | −15 | −37 |
| 7 | CUT | "Prior art in brief": strip calibration clauses, leave descriptive (St2) | −90 | −127 |
| 8 | ADD | B§4: inline "DAG" gloss (A3) | +7 | −120 |
| 9 | REWRITE | Conclusion (c): drop "CodeCRDT's own measured 5–10% semantic residue motivates exactly this layer" → "CodeCRDT measures a non-zero semantic residue after syntactic merge — evidence the judgment layer has real work to do" (S4) | −20 | −140 |
| 10 | CUT | Conclusion (b): drop the 5–10% sentence entirely (figure now lives only in B§2); the residue point is already made (S4) | −45 | −185 |
| 11 | CUT | Conclusion: delete the one-sentence contribution statement at top of Conclusion; (d) bullets carry it (St1, A1) | −110 | −295 |
| 12 | ADD | Conclusion (d): ASCII data-structure diagram, offset by trimming (d)'s abstract prose | +45 | −250 |
| 13 | CUT | Prose-craft bundle: em-dash thinning, "load-bearing" 5→2, "genuine" 4→1, "might want to"/"usually" hedges (P1/P2/P4/P5) | −60 | −310 |
| 14 | CUT | Conclusion MMP section: "MMP runs that" → "MMP specifies that"; drop the restated production hedge (S6) | −55 | −365 |
| 15 | CUT | Exec summary: MMP production hedge already removed in edit 4 — confirm references entry keeps the single surviving hedge (S6); no further Δ | 0 | −365 |
| 16 | CUT | Delete B§8 stub; fold its one InfiAgent/"Everything is Context" sentence into the "Prior art in brief" Claude Code bullet (St3) | −70 | −435 |
| 17 | CUT | Coverage-gaps list: shorten the CodeCRDT 5–10% gap entry — keep the bare "rate for prose/task artifacts unmeasured" point, drop the restated 600-trial caveat (S4) | −30 | −465 |
| 18 | CUT | **[whole-doc pass]** Instance sections 1–4: each ends with a "What it enables" paragraph partly restating the "Living-artifact version" above it; trim each by one sentence | −80 | −545 |
| 19 | CUT | **[whole-doc pass]** Conclusion (b): "You could not put open-ended judgment inside the structure, because open-ended judgment did not exist as a component you could instantiate cheaply and ubiquitously" — preceding sentences already said this; cut | −30 | −575 |
| 20 | CUT | **[whole-doc pass]** B§5 intro sentence "Where one reports a finding that looks like a threat, the finding usually has a time dimension the plan's framing already accounts for" — vague, and "usually" is an unearned hedge; cut (overlaps P4) | −22 | −597 |
| 21 | CUT | **[whole-doc pass]** Exec summary: the paragraph "What the plan builds, in plain terms ..." duplicates the Introduction's "What the plan proposes" almost verbatim; cut the exec-summary copy to a half-sentence pointer | −55 | −652 |
| 22 | CUT | **[whole-doc pass]** B§4 AutoGen/MetaGPT/ChatDev: the "central-coordinator confrontation" lead-in and the closing "What is unbuilt is not decentralized coordination; it is the living artifact" restate the section's own point made three paragraphs earlier; trim the lead-in | −35 | −687 |

**Whole-document pass result:** found ~640 words of reviewer-listed cuts plus an
additional ~340 words the reviewer did not list (edits 18–22 plus the deeper trims
in 4, 7, 11). Total CUT ≈ 822 words; total ADD ≈ 135 words.

---

## Projected net word change

- Total added: ~135 words (3 new citation sentences, DAG gloss, ASCII diagram).
- Total cut: ~822 words.
- **Projected net change: −687 words.**

This clears the step-9 target (net reduction ≥520) with margin. The document
moves from ~11,700 words to ~11,010 words. The cut is net negative; the apply
pass must word-count before and after to confirm. If the apply pass nets positive
or flat, it has failed and must be redone.

---

## Convergence note

Cycle 5 surfaced one genuine uncited prior-art paper (MEMOREPAIR), one
worth-citing near-miss (CORAL), and one citation whose scope the reviewer
over-stated (Consensus Trap — real, but cited for failure modes its abstract does
not support; corrected here). After this cycle's edits the citation front is
closed and the gloss-stacking Block-3 pattern is fixed. Remaining items (A4
superposition, A5 stigmergy, P3 phrasing variety) are phrasing-only. Recommend one
final phrasing-only Cycle 6, then stop.
