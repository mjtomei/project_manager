# Review Response — Cycle 5 (user-model literature review)

Date: 2026-05-14
Responding to: `REVIEW_CYCLE_5_USERMODEL.md`

Cycle 5 surfaced 19 findings (17 phrasing nits, 2 substantive). The user clarification reshapes how the two substantive findings should be handled — both shrink, and the broader framing of the plan tightens.

## Framing clarification (user-supplied, applies across the loop)

> "We can go with a three axis IV. In fact, if we have some way to search for new IVs or propose more ourselves, that would only be good for us. There is not really a huge worry from not pre registering here because our target is a better engineering outcome ultimately which is measurable, not a statistical confidence in a correlation."

This reframes Phase 1's factor-analysis step substantially:

- **Not a falsification gate.** The two-meta-axis structure (intellectual + moral peer-ness) is a *starting hypothesis* informed by SCM (and Goodwin's competing three-factor view). It is not a commitment. Whatever structure emerges from the factor analysis — two, three, or N axes — is the structure the plan adopts for Phase 2.
- **Three (or more) axes are welcome, not a problem.** If Goodwin's three-factor structure (morality + sociability + competence) shows up, fine — Phase 2 aggregates along three axes. If a fourth emerges (e.g., a "time-pressure" or "domain-match" axis the plan didn't predict), even better.
- **The target is engineering improvement, not statistical-confidence-on-a-correlation.** Phase 2's DV is task performance on gradable benchmarks. If the plan delivers measurable performance improvement, the structure that gets us there is the structure that matters, regardless of how cleanly it matches the social-psychology priors.

This shrinks both substantive findings:

## Substantive findings

### S1. "Empirically agnostic" framing papers over a real problem (Goodwin's three factors would *falsify* not revise) — DOWNGRADED to a small edit

**Partial disagree.** The Cycle 5 reviewer is right that the prior "agnostic" framing was sloppy if treated as a falsification gate. With the user clarification, there is no falsification gate. The framing tightens to:

> "The plan's two-meta-axis structure (intellectual + moral peer-ness) is a starting hypothesis informed by SCM's two-dimensional warmth/competence framework. Goodwin et al. 2014's three-factor view (morality + sociability + competence) is an alternative; further alternatives may exist. Phase 1's exploratory factor analysis adopts whichever structure the data reveal — two, three, or more — and Phase 2's aggregation proceeds along those axes. The plan is not committed to two-meta-axes; it is committed to *whatever structure the model actually represents.* New axes the plan didn't predict are a positive finding, not a problem."

**Edit (lit review)**: rewrite the SCM-vs-Goodwin passage to drop the "agnostic" hedge and replace with the explicit "two-axes is a starting hypothesis; the data is the authority" framing. Add an explicit welcome for new axes the plan didn't predict.

**Edit (plan)**: surface the same framing to `plan-66d430f.md`'s Phase 1 construct-validity test sub-PR. The "empirically agnostic between SCM and Goodwin" line becomes "the plan adopts whichever structure Phase 1 reveals; the two-axis prediction is a starting point, not a commitment."

### S2. "Falsifiability lead" doesn't say what happens after falsification — DROPPED

**Disagree, drop.** With the user clarification, there is no falsification step. Phase 1's exploration is just exploration — it produces a structure, Phase 2 uses it. The "what happens if falsified" question doesn't apply.

**Edit (lit review)**: rewrite Phase 1's novelty paragraph. Drop the "falsifiability lead" framing. Replace with:

> "Phase 1's contribution is the *map of structure* — whatever shape peer-ness or peer-ness-adjacent representations take in the residual stream. The plan's two-meta-axis prediction (intellectual + moral) is a starting hypothesis informed by social-psychology priors (SCM, Goodwin), but the factor analysis is exploration — Phase 2 aggregates along whichever axes the data reveal. The novelty is in producing the map for a specific construct (the model's user-modeling representation, narrower than Choi/Transluce's broad user-attribute decoding); the rigor is in letting the data dictate the structure rather than forcing it through a pre-registered confirmatory test."

This also addresses one of the Cycle 4 reviewer's worries — the "either way" hinge that read hedgy. The new framing isn't hedgy; it's explicit about exploration.

## Phrasing nits (17 items)

Roll up into the edit pass without per-item analysis. The Cycle 5 review has the proposed replacements.

## Edits checklist

1. Rewrite the SCM-vs-Goodwin passage in §1 to drop "empirically agnostic" hedge. Replace with explicit "two-axes is a starting hypothesis; the data is the authority; new axes welcome" framing.
2. Rewrite Phase 1's novelty paragraph in §7 to drop the "falsifiability lead." Replace with the "map of structure" framing above.
3. Update the predicted-outcomes table: the "factor structure differs from prediction" rows become "factor structure shows N factors; plan adopts the N-axis structure for Phase 2." Less drama, more honesty.
4. Apply the 17 Cycle 5 phrasing-nit edits per the review's specific text.
5. Plan-owner item: update `plan-66d430f.md`'s Phase 1 construct-validity test to drop the "empirically agnostic" framing and replace with the data-is-authority version.

## Note on Goodwin verification

Cycle 5's reviewer noted they couldn't verify Goodwin's abstract directly due to paywall. The Cycle 4 edit-application agent's verification appears to have been bibliographic-info-only (volume, issue, pages) rather than abstract content. The lit review's characterization of Goodwin's claim ("morality is a separable third dimension") is the standard summary of that paper — it appears in many secondary sources — but the response acknowledges that direct abstract verification was incomplete. The Goodwin citation can stand with this caveat noted.

## Convergence

After this edit pass, the loop on the user-model lit review is **closed**. Cycle 5 was substantially nit-territory; the two substantive findings were caused by an over-claim (the "agnostic" framing) that the user clarification removes. No Cycle 6.

Carryover obligations (same shape as the regression-loop lit review's closure):
- `plan-66d430f.md`'s Phase 1 construct-validity test needs the data-is-authority framing applied (already partly applied per the Cycle 4 plan note; finish in this pass).
- The lit review now states the plan welcomes IV-discovery beyond the predicted two-axis structure. If the plan owner wants this as an explicit experimental aim (e.g., add an "IV-discovery" sub-PR to Phase 1), that's a plan edit, not a lit-review edit.
